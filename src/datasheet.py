#reconize reoccuring patterns
#reconize common purchases
#reconize time/date of purchases
#reconize payment Transaction_Type
#payment frequency

from collections import Counter, defaultdict
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


def irregular(df, min_item_history=3):
    """Find purchase outliers using only transactions earlier in the same sheet.

    A new description is cold-started: it is not treated as suspicious merely
    because its amount or price has never appeared before.
    """
    if min_item_history < 1:
        raise ValueError("min_item_history must be positive")

    paid = df[(df["Amount"] > 0) & df["Date"].notna()].sort_values("Date", kind="stable")
    history_by_item = defaultdict(list)
    history_by_price = Counter()
    history_by_day = Counter()
    rows = []

    for row, purchase in paid.iterrows():
        item = str(purchase["Item"])
        item_key = " ".join(item.casefold().split())
        amount = float(purchase["Amount"])
        day = purchase["Date"].normalize()
        prior_amounts = history_by_item[item_key]
        prior_count = len(prior_amounts)
        median_amount = mad_amount = threshold_amount = None
        signals = []

        if prior_count >= min_item_history:
            prior = pd.Series(prior_amounts, dtype="float64")
            median_amount = float(prior.median())
            mad_amount = float((prior - median_amount).abs().median())
            threshold_amount = median_amount + max(3 * 1.4826 * mad_amount, median_amount * 0.5)
            if amount > threshold_amount:
                signals.append(
                    f"amount ${amount:.2f} exceeds the prior {prior_count}-purchase baseline "
                    f"(median ${median_amount:.2f}, upper threshold ${threshold_amount:.2f})"
                )

        prior_same_price = history_by_price[(item_key, amount, day)]
        prior_same_day = history_by_day[day]
        if prior_same_price:
            signals.append(f"duplicate charge: {prior_same_price} earlier matching charge(s) for this item and amount today")
        elif prior_same_day >= 2:
            signals.append(f"one of multiple same-day purchases: {prior_same_day} earlier purchases today")

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
    return rows


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
