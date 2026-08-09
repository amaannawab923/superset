import glob, pantab, pandas as pd
from tableauhyperapi import HyperProcess, Telemetry, Connection

hyper = glob.glob("extracted/**/*.hyper", recursive=True)[0]

# introspect
with HyperProcess(Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU) as hp:
    with Connection(hp.endpoint, hyper) as conn:
        tbls = [t for s in conn.catalog.get_schema_names()
                  for t in conn.catalog.get_table_names(s)]
        print("TABLES:", [str(t) for t in tbls])

# read into pandas
frames = pantab.frames_from_hyper(hyper)
# pick the frame that has a Sales column (case-insensitive)
name, df = None, None
for k, v in frames.items():
    if any(c.lower() == "sales" for c in v.columns):
        name, df = k, v; break
if df is None:
    name, df = next(iter(frames.items()))

print("MAIN FRAME:", str(name), "shape:", df.shape)
print("COLUMNS:", list(df.columns))
sales = next((c for c in df.columns if c.lower() == "sales"), None)
if sales:
    print(f"SUM(Sales) = {df[sales].sum():,.0f}   (Tableau shows 1,359,501)")
    print(f"SUM(Profit) = {df[next(c for c in df.columns if c.lower()=='profit')].sum():,.0f}")
    print(f"COUNT(distinct Order ID) = {df[next(c for c in df.columns if c.lower().replace(' ','')=='orderid')].nunique():,}")
# save a clean CSV for loading
df.to_csv("superstore_overview.csv", index=False)
print("wrote superstore_overview.csv rows=", len(df))
