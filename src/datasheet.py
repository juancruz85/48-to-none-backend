#reconize reoccuring patterns
#reconize common purchases
#reconize time/date of purchases
#reconize payment Transaction_Type
#payment frequency

import sys
import pandas as pd

def load(paths):
    df = pd.concat([pd.read_csv(p) for p in paths], ignore_index=True)
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.rename(columns={"Amount (USD)": "Amount"})
    df = df.sort_values("Date", kind="stable").reset_index(drop=True)
    df["Category"] = df["Item"].map(categorize)
    df["Transaction_Type"] = df.apply(transaction_type, axis=1)
    return df

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
    """Items bought >= min_count times, with typical gap between charges."""
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
            "Median gap (days)": gaps.median(),
            "Typical day of month": g["Date"].dt.day.mode().iloc[0],
            "Prices": ", ".join(f"{p:.2f}" for p in sorted(g["Amount"].unique())),
        })
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
    months = paid["Date"].dt.to_period("M")
    span = (months.max() - months.min()).n + 1
    return {
        "paid_charges": len(paid),
        "months_spanned": span,
        "charges_per_month": round(len(paid) / span, 2),
        "months_with_a_charge": months.nunique(),
        "median_days_between_any_charges": paid["Date"].diff().dt.days.median(),
    }


"""
MUST ROUTE ALL PRINT STATEMENTS AS RETURN VALUES THEN GIVE THAT TO THE AI MODEL.

THEN FINAL WILL ROUTE TO DASHBOARD.
"""



def main(paths):
    df = load(paths)
    paid = df[df["Amount"] > 0]
    pd.set_option("display.width", 140)

    print(f"Rows: {len(df)} | paid: {len(paid)} | $0: {(df.Amount == 0).sum()} | "
          f"total spent: ${paid.Amount.sum():,.2f}\n")

    print("== Recurring patterns ==")
    print(recurring_patterns(paid).to_string(index=False), "\n")

    by_cat, by_price = common_purchases(paid)
    print("== Common purchases (by category) ==")
    print(by_cat.round(2), "\n")
    print("== Most common prices ==")
    print(by_price, "\n")

    t = time_patterns(paid)
    print("== Time / date of purchases ==")
    print("By year:\n", t["by_year"].round(2), "\n")
    print("By weekday:\n", t["by_weekday"].round(2), "\n")
    print("By day of month (top):\n", t["by_day_of_month"], "\n")
    print("Highest-spend months:\n", t["top_months"].round(2), "\n")
    print(f"Average paid month: ${t['avg_month']:.2f}\n")

    print("== Transaction types ==")
    print(type_summary(df).round(2), "\n")

    print("== Payment frequency ==")
    for k, v in payment_frequency(paid).items():
        print(f"{k}: {v}")

if __name__ == "__main__":
    args = sys.argv[1:] or ["play_store_history.csv", "play_store_history_2022-2025.csv"]
    main(args)