#reconize reoccuring patterns
#reconize common purchases
#reconize time/date of purchases
#reconize payment Transaction_Type
#payment frequency

import sys
import pandas as pd

from .mattsheet import D_dates


def prepare(df):
    #puts any input layout into the one the analysis uses: Date, Item, Amount, Category, Transaction_Type.
    df = df.copy()
    bank_layout = "Description" in df.columns and "Item" not in df.columns
    df = df.rename(columns={"Amount (USD)": "Amount", "Description": "Item"})
    df["Date"] = D_dates(df["Date"])
    df["Amount"] = pd.to_numeric(df["Amount"], errors="coerce")
    if bank_layout:
        #bank exports record money spent as negative, the analysis counts spending as positive.
        df["Amount"] = -df["Amount"]
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


def irregular(df):
    #shortlist of paid purchases that do not fit the person's normal pattern. the model decides which are fraud.
    #df must come from prepare(). returns one dict per purchase with the facts and the signals that put it on the list.
    paid = df[df["Amount"] > 0]
    if paid.empty:
        return []
    usual = paid["Amount"].median()
    times_bought = paid.groupby(["Item", "Amount"])["Amount"].transform("count")
    times_seen = paid.groupby("Item")["Amount"].transform("count")
    charges_that_day = paid.groupby("Date")["Amount"].transform("count")
    same_charge_that_day = paid.groupby(["Date", "Item", "Amount"])["Amount"].transform("count")

    rows = []
    for row, purchase in paid.iterrows():
        signals = []
        if times_bought[row] == 1:
            signals.append("only time this item was bought at this price")
        if purchase["Amount"] >= 3 * usual:
            signals.append(f"amount is at least 3 times the usual ${usual:.2f}")
        if same_charge_that_day[row] > 1:
            signals.append(f"charged {same_charge_that_day[row]} times for the same thing on the same day")
        elif charges_that_day[row] >= 3:
            signals.append(f"one of {charges_that_day[row]} charges on the same day")
        if signals:
            rows.append({
                "row": int(row),
                "date": str(purchase["Date"].date()),
                "item": purchase["Item"],
                "amount": float(purchase["Amount"]),
                "times_bought": int(times_bought[row]),
                "times_seen": int(times_seen[row]),
                "signals": signals,
            })
    return rows


"""
ALL PRINT STATEMENTS ARE ROUTED AS A RETURN VALUE (report) WHICH IS GIVEN TO THE AI MODEL.

THEN FINAL WILL ROUTE TO DASHBOARD.
"""

def report(df):
    #df must come from prepare() or load(). returns the full analysis as text.
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
