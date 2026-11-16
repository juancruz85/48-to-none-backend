#reconize reoccuring patterns
#reconize common purchases
#reconize time/date of purchases
#reconize payment Transaction_Type
#payment frequency

from collections import Counter, defaultdict
import math
import sys
import pandas as pd

from .mattsheet import D_dates


def prepare(df):
    df = df.copy()
    bank_layout = "Description" in df.columns and "Item" not in df.columns
    df = df.rename(columns={"Amount (USD)": "Amount", "Description": "Item"})
    df["Date"] = D_dates(df["Date"])
    df["Amount"] = pd.to_numeric(df["Amount"], errors="coerce")
    if bank_layout:
        #bank exports record money spent as negative, the analysis counts spending as positive.
        df["Amount"] = -df["Amount"]
    #an item column of only numbers is read as numbers, and the rest of the analysis expects text.
    df["Item"] = df["Item"].astype(str)
    df["Category"] = df["Item"].map(categorize)
    if "Transaction_Type" not in df.columns:
        df["Transaction_Type"] = df.apply(transaction_type, axis=1)
    #oldest first, so the gaps between charges come out positive.
    #row labels are kept, so a row here is the same row in the sheet.
    return df.sort_values("Date", kind="stable")


def load(paths):
    return prepare(pd.concat([pd.read_csv(p) for p in paths], ignore_index=True))

CATEGORY_RULES = [
    ("roblox premium", "Roblox Premium"),
    ("premium individual", "Spotify"),
    ("chatgpt", "ChatGPT Plus"),
    ("battle pass", "Battle Pass VIP"),
    ("season pass", "Season Pass Plus"),
    ("gems", "Gems"),
    ("authorization", "Warship keys/boxes"),
    ("box with", "Warship keys/boxes"),
    ("extra large box", "Warship keys/boxes"),
    ("flagship", "Warship keys/boxes"),
    ("vault pass", "Warship passes"),
    ("winter standoff", "Warship passes"),
    ("tiny bag", "Tiny bag (city game)"),
    ("google play credit", "Play credit"),
]

def categorize(item):
    s = item.lower()
    for key, cat in CATEGORY_RULES:
        if key in s:
            return cat
    return "Other"

SUBSCRIPTIONS = {"Roblox Premium", "Spotify", "ChatGPT Plus"}
PASSES = {"Battle Pass VIP", "Season Pass Plus", "Warship passes"}

def transaction_type(row):
    if row["Amount"] == 0:
        return "Free / $0"
    if row["Category"] in SUBSCRIPTIONS:
        return "Subscription"
    if row["Category"] in PASSES:
        return "Seasonal pass"
    return "One-time in-app purchase"

def recurring_patterns(paid, min_count=3):
    rows = []
    for cat, g in paid.groupby("Category"):
        if len(g) < min_count:
            continue
        gaps = g["Date"].diff().dt.days.dropna()
        rows.append({
            "Category": cat,
            "Charges": len(g),
            "First": g["Date"].min().date(),
            "Last": g["Date"].max().date(),
            "Median gap (days)": gaps.median() if not gaps.empty else None,
            "Typical day of month": g["Date"].dt.day.mode().iloc[0] if not g["Date"].dt.day.mode().empty else None,
            "Prices": ", ".join(f"{p:.2f}" for p in sorted(g["Amount"].unique())),
        })
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values("Charges", ascending=False)

def common_purchases(paid):
    by_cat = (paid.groupby("Category")["Amount"]
                  .agg(Purchases="count", Total="sum")
                  .sort_values("Total", ascending=False))
    by_price = paid["Amount"].value_counts().head(8).rename("Times bought")
    return by_cat, by_price

def time_patterns(paid):
    """Dates only (no time-of-day in the data)."""
    p = paid.assign(Year=paid["Date"].dt.year,
                    Month=paid["Date"].dt.to_period("M"),
                    Weekday=paid["Date"].dt.day_name(),
                    Day=paid["Date"].dt.day)
    weekday_order = ["Monday", "Tuesday", "Wednesday", "Thursday",
                     "Friday", "Saturday", "Sunday"]
    return {
        "by_year": p.groupby("Year")["Amount"].agg(Purchases="count", Total="sum"),
        "by_weekday": (p.groupby("Weekday")["Amount"].agg(Purchases="count", Total="sum")
                        .reindex(weekday_order)),
        "by_day_of_month": p["Day"].value_counts().head(8).rename("Purchases"),
        "top_months": p.groupby("Month")["Amount"].sum().sort_values(ascending=False).head(6),
        "avg_month": p.groupby("Month")["Amount"].sum().mean(),
    }

def type_summary(df):
    return (df.groupby("Transaction_Type")["Amount"]
              .agg(Transactions="count", Total="sum")
              .sort_values("Total", ascending=False))

def payment_frequency(paid):
    if paid.empty:
        return {
            "paid_charges": 0,
            "months_spanned": 0,
            "charges_per_month": 0,
            "months_with_a_charge": 0,
            "median_days_between_any_charges": None,
        }
    months = paid["Date"].dt.to_period("M")
    span = (months.max() - months.min()).n + 1
    return {
        "paid_charges": len(paid),
        "months_spanned": span,
        "charges_per_month": round(len(paid) / span, 2) if span > 0 else 0,
        "months_with_a_charge": months.nunique(),
        "median_days_between_any_charges": paid["Date"].diff().dt.days.median(),
    }


def irregular(df, min_item_history=3, min_day_history=10):
    """Find purchase outliers using only transactions earlier in the same sheet.

    A new description is cold-started: it is not treated as suspicious merely
    because its amount or price has never appeared before.

    Three signals:
    - amount: at least double what this item normally costs (and past its usual spread).
    - duplicate: the same item at the same amount earlier the same day.
    - burst: several unfamiliar purchases in one day, more than this person's days normally hold, that
      together cost more than this person's days normally cost. Both have to be true: a day of many small
      new purchases (a day out) is not a burst, and neither is a person who buys from new sellers all the time.
      Routine purchases do not count towards a burst and are never part of one: groceries are not
      suspicious because other things were bought that day. A purchase is routine when the item was
      bought at least `min_item_history` times before and the amount is normal for it, or when the
      item was charged this exact amount before (a bill or subscription).
      How many purchases a day normally holds and what a day normally costs come from the person's own
      earlier days, so a burst needs `min_day_history` earlier days with purchases before it can fire.
    """
    if min_item_history < 1 or min_day_history < 1:
        raise ValueError("min_item_history and min_day_history must be positive")

    paid = df[(df["Amount"] > 0) & df["Date"].notna()].sort_values("Date", kind="stable")
    history_by_item = defaultdict(list)
    history_by_price = Counter()
    history_by_day = Counter()
    #how many purchases each earlier day ended with, to know what a busy day looks like for this person.
    earlier_day_counts = []
    #what each earlier day cost in all, to know what an expensive day looks like for this person.
    earlier_day_totals = []
    current_day = None
    busy_day = None
    busy_spend = None
    unfamiliar_today = 0
    spend_today = 0.0
    unfamiliar_spend_today = 0.0
    rows = []

    for row, purchase in paid.iterrows():
        item = str(purchase["Item"])
        item_key = " ".join(item.casefold().split())
        amount = float(purchase["Amount"])
        day = purchase["Date"].normalize()
        if day != current_day:
            if current_day is not None:
                earlier_day_counts.append(history_by_day[current_day])
                earlier_day_totals.append(spend_today)
            current_day = day
            unfamiliar_today = 0
            spend_today = 0.0
            unfamiliar_spend_today = 0.0
            busy_day = None
            busy_spend = None
            if len(earlier_day_counts) >= min_day_history:
                #a busy day has more than double their usual day's purchases, and never fewer than 3.
                #the median is used so a few busy days (or a few days of fraud) do not become the new normal.
                usual = float(pd.Series(earlier_day_counts, dtype="float64").median())
                busy_day = max(3, math.ceil(2 * usual) + 1)
                #an expensive day costs more than double their usual day, and past the usual spread
                #(the same rule as for one item's amount).
                totals = pd.Series(earlier_day_totals, dtype="float64")
                usual_total = float(totals.median())
                total_spread = float((totals - usual_total).abs().median())
                busy_spend = usual_total + max(3 * 1.4826 * total_spread, usual_total)
        prior_amounts = history_by_item[item_key]
        prior_count = len(prior_amounts)
        median_amount = mad_amount = threshold_amount = None
        #charged this exact amount before: a bill or a subscription.
        routine = amount in prior_amounts
        signals = []

        if prior_count >= min_item_history:
            prior = pd.Series(prior_amounts, dtype="float64")
            median_amount = float(prior.median())
            mad_amount = float((prior - median_amount).abs().median())
            #what an item costs moves around (a restaurant bill, an online order), and a few purchases are not
            #enough to know by how much. so the threshold is never under double the usual amount.
            threshold_amount = median_amount + max(3 * 1.4826 * mad_amount, median_amount)
            routine = routine or amount <= threshold_amount
            if amount > threshold_amount:
                signals.append(
                    f"amount ${amount:.2f} exceeds the prior {prior_count}-purchase baseline "
                    f"(median ${median_amount:.2f}, upper threshold ${threshold_amount:.2f}), "
                    f"{amount / median_amount:.1f} times the usual amount"
                )

        prior_same_price = history_by_price[(item_key, amount, day)]
        prior_same_day = history_by_day[day]
        if prior_same_price:
            signals.append(f"duplicate charge: {prior_same_price} earlier matching charge(s) for this item and amount today")
        elif (not routine and busy_day is not None and unfamiliar_today + 1 >= busy_day
              and unfamiliar_spend_today + amount > busy_spend):
            signals.append(
                f"burst of unfamiliar purchases: number {unfamiliar_today + 1} today that is not one of "
                f"this person's usual purchases ({prior_same_day} earlier purchases today in all), "
                f"${unfamiliar_spend_today + amount:.2f} of unfamiliar spending today against "
                f"${usual_total:.2f} on a usual day, "
                f"{(unfamiliar_spend_today + amount) / max(usual_total, 0.01):.1f} times a usual day"
            )

        if signals:
            rows.append({
                "row": int(row),
                "date": str(purchase["Date"].date()),
                "item": item,
                "amount": amount,
                "times_bought": int(prior_same_price),
                "times_seen": int(prior_count),
                "baseline": {
                    "ready": prior_count >= min_item_history,
                    "history_count": int(prior_count),
                    "minimum_history": min_item_history,
                    "median_amount": round(median_amount, 2) if median_amount is not None else None,
                    "mad_amount": round(mad_amount, 2) if mad_amount is not None else None,
                    "upper_threshold": round(threshold_amount, 2) if threshold_amount is not None else None,
                },
                "signals": signals,
            })

        # Update after scoring so this transaction can never affect its own baseline.
        history_by_item[item_key].append(amount)
        history_by_price[(item_key, amount, day)] += 1
        history_by_day[day] += 1
        spend_today += amount
        if not routine:
            unfamiliar_today += 1
            unfamiliar_spend_today += amount
    return rows


def patterns(df, window_days=30, min_recent=6, growth=2.0):
    """Find sellers whose charges keep getting more frequent, however small each charge is.

    irregular() looks at one purchase at a time, so a stream of $1 charges on different days never
    stands out there. This looks at one seller over time instead: a charge is part of a rising pattern
    when the `window_days` up to it hold at least `min_recent` charges from that seller and at least
    `growth` times what the seller's earlier history averaged over the same length of time.
    Like irregular(), every charge is judged using only the charges before it.

    This is not a fraud verdict. Each pattern is one question for the model (review_patterns in model.py),
    which decides whether the person should take a look.
    """
    if window_days < 1 or min_recent < 2 or growth <= 1:
        raise ValueError("patterns needs a positive window, at least 2 recent charges and growth above 1")

    paid = df[(df["Amount"] > 0) & df["Date"].notna()].sort_values("Date", kind="stable")
    keys = paid["Item"].map(lambda value: " ".join(str(value).casefold().split()))
    window = pd.Timedelta(days=window_days)
    found = []

    for _, group in paid.groupby(keys, sort=False):
        if len(group) <= min_recent:
            continue
        dates = group["Date"].tolist()
        rows = [int(row) for row in group.index]
        rising = []
        peak = None
        start = 0
        for index, when in enumerate(dates):
            while dates[start] <= when - window:
                start += 1
            recent = index - start + 1
            earlier = start
            earlier_days = (when - window - dates[0]).days
            #a seller needs a full window of earlier history before "more than before" means anything.
            if earlier < 1 or earlier_days < window_days:
                continue
            earlier_rate = earlier / (earlier_days / window_days)
            if recent >= max(min_recent, growth * earlier_rate):
                rising.append(index)
                if peak is None or recent > peak["recent"]:
                    peak = {"recent": recent, "earlier_rate": earlier_rate, "as_of": when}
        if not rising:
            continue

        monthly = group.assign(_month=group["Date"].dt.to_period("M")).groupby("_month")["Amount"].agg(["count", "sum"])
        months = pd.period_range(monthly.index.min(), monthly.index.max(), freq="M")
        monthly = monthly.reindex(months, fill_value=0)
        item = str(group["Item"].mode().iloc[0])
        total = float(group["Amount"].sum())
        flagged = [rows[index] for index in rising]
        found.append({
            "kind": "rising_charges",
            "item": item,
            "rows": flagged,
            "charges": int(len(group)),
            "total": round(total, 2),
            "median_amount": round(float(group["Amount"].median()), 2),
            "first": str(dates[0].date()),
            "last": str(dates[-1].date()),
            "rising_since": str(dates[rising[0]].date()),
            "rising_charges": len(flagged),
            "rising_total": round(float(group["Amount"].iloc[rising].sum()), 2),
            "peak": {
                "window_days": window_days,
                "charges": int(peak["recent"]),
                "earlier_charges_per_window": round(float(peak["earlier_rate"]), 1),
                "as_of": str(peak["as_of"].date()),
            },
            "months": [
                {"month": str(month), "charges": int(row["count"]), "total": round(float(row["sum"]), 2)}
                for month, row in monthly.iterrows()
            ],
            "signal": (
                f"{int(peak['recent'])} charges from {item} in the {window_days} days to {peak['as_of'].date()}, "
                f"up from about {peak['earlier_rate']:.0f} per {window_days} days before; "
                f"{len(group)} charges totalling ${total:,.2f} since {dates[0].date()}"
            ),
        })
    #the patterns that cost the most come first.
    return sorted(found, key=lambda pattern: (-pattern["rising_total"], pattern["item"]))


def profile(df, max_items=8, max_months=6):
    """Build compact whole-sheet context for batched fraud review."""
    paid = df[df["Amount"] > 0]
    if paid.empty:
        return {
            "transactions": len(df),
            "paid_transactions": 0,
            "median_paid_amount": None,
            "frequent_items": [],
            "recent_monthly_spend": [],
        }

    frequent = (
        paid.groupby("Item")["Amount"]
        .agg(purchases="count", median_amount="median")
        .sort_values(["purchases", "median_amount"], ascending=[False, False])
        .head(max_items)
    )
    monthly = (
        paid.assign(Month=paid["Date"].dt.to_period("M"))
        .groupby("Month")["Amount"]
        .sum()
        .sort_index()
        .tail(max_months)
    )
    return {
        "transactions": len(df),
        "paid_transactions": len(paid),
        "median_paid_amount": round(float(paid["Amount"].median()), 2),
        "frequent_items": [
            {
                "item": " ".join(str(item).split())[:80],
                "purchases": int(row.purchases),
                "median_amount": round(float(row.median_amount), 2),
            }
            for item, row in frequent.iterrows()
        ],
        "recent_monthly_spend": [
            {"month": str(month), "amount": round(float(amount), 2)}
            for month, amount in monthly.items()
        ],
    }


def baseline(df, min_overall_history=10, min_item_history=3):
    """Build a deterministic, versioned summary of one user's historical spending.

    This is descriptive state for downstream rules or model context, not a fraud
    verdict. Amounts use the normalized positive-spending convention from prepare().
    """
    if min_overall_history < 1 or min_item_history < 1:
        raise ValueError("baseline history minimums must be positive")

    paid = df[(df["Amount"] > 0) & df["Date"].notna()].copy()
    paid["_baseline_item"] = paid["Item"].map(lambda value: " ".join(str(value).casefold().split()))

    def amount_stats(values):
        values = pd.to_numeric(values, errors="coerce").dropna()
        if values.empty:
            return {"median_amount": None, "mad_amount": None, "p95_amount": None}
        median = float(values.median())
        mad = float((values - median).abs().median())
        return {
            "median_amount": round(median, 2),
            "mad_amount": round(mad, 2),
            "p95_amount": round(float(values.quantile(0.95)), 2),
        }

    overall = amount_stats(paid["Amount"])
    monthly_paid = paid.assign(_month=paid["Date"].dt.to_period("M")).groupby("_month")["Amount"].sum()
    if monthly_paid.empty:
        monthly = monthly_paid
    else:
        months = pd.period_range(monthly_paid.index.min(), monthly_paid.index.max(), freq="M")
        monthly = monthly_paid.reindex(months, fill_value=0)
    monthly_stats = amount_stats(monthly)
    all_gaps = paid.sort_values("Date")["Date"].diff().dt.total_seconds().div(86400).dropna()

    item_baselines = []
    for key, group in paid.groupby("_baseline_item", sort=False):
        group = group.sort_values("Date", kind="stable")
        gaps = group["Date"].diff().dt.total_seconds().div(86400).dropna()
        display_item = str(group["Item"].mode().iloc[0]) if not group["Item"].mode().empty else str(group["Item"].iloc[0])
        item_baselines.append({
            "item": display_item,
            "key": key,
            "transaction_count": int(len(group)),
            "ready": len(group) >= min_item_history,
            **amount_stats(group["Amount"]),
            "median_gap_days": round(float(gaps.median()), 2) if not gaps.empty else None,
        })
    item_baselines.sort(key=lambda item: (-item["transaction_count"], item["key"]))

    return {
        "schema_version": 1,
        "method": "per_user_descriptive_median_mad",
        "amount_unit": "as_provided_by_input",
        "transaction_count": int(len(df)),
        "paid_transaction_count": int(len(paid)),
        "ready": len(paid) >= min_overall_history,
        "minimum_history": {
            "overall_paid_transactions": min_overall_history,
            "per_item_transactions": min_item_history,
        },
        "as_of": str(paid["Date"].max().date()) if not paid.empty else None,
        "overall": {
            **overall,
            "median_monthly_spend": monthly_stats["median_amount"],
            "mad_monthly_spend": monthly_stats["mad_amount"],
            "median_gap_days": round(float(all_gaps.median()), 2) if not all_gaps.empty else None,
        },
        "items": item_baselines,
    }


"""
ALL PRINT STATEMENTS ARE ROUTED AS A RETURN VALUE (report) WHICH IS GIVEN TO THE AI MODEL.

THEN FINAL WILL ROUTE TO DASHBOARD.
"""

def report(df):
    #df must come from prepare() or load().
    paid = df[df["Amount"] > 0]
    by_cat, by_price = common_purchases(paid)
    t = time_patterns(paid)
    lines = [
        f"Rows: {len(df)} | paid: {len(paid)} | $0: {(df.Amount == 0).sum()} | "
        f"total spent: ${paid.Amount.sum():,.2f}",
        "",
        "== Recurring patterns ==",
        recurring_patterns(paid).to_string(index=False),
        "",
        "== Common purchases (by category) ==",
        by_cat.round(2).to_string(),
        "",
        "== Most common prices ==",
        by_price.to_string(),
        "",
        "== Time / date of purchases ==",
        "By year:",
        t["by_year"].round(2).to_string(),
        "By weekday:",
        t["by_weekday"].round(2).to_string(),
        "By day of month (top):",
        t["by_day_of_month"].to_string(),
        "Highest-spend months:",
        t["top_months"].round(2).to_string(),
        f"Average paid month: ${t['avg_month']:.2f}",
        "",
        "== Transaction types ==",
        type_summary(df).round(2).to_string(),
        "",
        "== Payment frequency ==",
    ]
    lines += [f"{k}: {v}" for k, v in payment_frequency(paid).items()]
    return "\n".join(lines)


def main(paths):
    print(report(load(paths)))


if __name__ == "__main__":
    args = sys.argv[1:] or ["play_store_history.csv", "play_store_history_2022-2025.csv"]
    main(args)
