import pandas as pd
df = pd.read_csv("superstore_overview.csv", parse_dates=["Order Date","Ship Date"])
target = 1359501
print("rows:", len(df), "| date range:", df["Order Date"].min().date(), "->", df["Order Date"].max().date())
print(f"RAW total Sales = {df['Sales'].sum():,.0f}   target = {target:,}")
print()
print("--- Sales by YEAR ---")
by_year = df.groupby(df["Order Date"].dt.year)["Sales"].sum()
for y,v in by_year.items(): print(f"  {y}: {v:,.0f}")
print()
# hypothesis: latest full year
latest_year = df["Order Date"].dt.year.max()
ly = df[df["Order Date"].dt.year==latest_year]["Sales"].sum()
print(f"latest year ({latest_year}) sales = {ly:,.0f}")
# hypothesis: trailing 12 months from max date
maxd = df["Order Date"].max()
t12 = df[df["Order Date"] > (maxd - pd.DateOffset(months=12))]["Sales"].sum()
print(f"trailing 12 months = {t12:,.0f}")
# by segment
print("\n--- Sales by SEGMENT ---")
for s,v in df.groupby("Segment")["Sales"].sum().items(): print(f"  {s}: {v:,.0f}")
# search: which single filter gets closest to target?
print("\n--- closeness to target ---")
for label,val in [("latest year",ly),("trailing12m",t12)]:
    print(f"  {label}: {val:,.0f}  (off by {val-target:+,.0f})")
