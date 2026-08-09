"""Runs INSIDE the superset-light container (app context).
Loads the extracted table into the analytics DB, builds/refreshes a Superset
dataset, then executes every SIMPLE_AGG metric THROUGH Superset's own query
engine and diffs the result against the pandas ground truth.  This is the
numeric-diff gate: a chart is only "migrated" if Superset returns the same
number the source workbook does.
"""
import json
import pandas as pd

from superset.app import create_app

PLAN = "/tmp/migration_plan.json"
PARQUET = "/tmp/mig_primary.parquet"
DB_NAME = "BI Spike"
TABLE = "mig_orders"
TOL = 0.005  # 0.5% relative tolerance

app = create_app()
with app.app_context():
    from superset import db
    from superset.models.core import Database
    from superset.connectors.sqla.models import SqlaTable

    plan = json.load(open(PLAN))
    df = pd.read_parquet(PARQUET)

    database = db.session.query(Database).filter_by(database_name=DB_NAME).first()
    assert database, f"Database {DB_NAME!r} not found"

    # 1. load the extracted data into the analytics DB
    with database.get_sqla_engine() as engine:
        df.to_sql(TABLE, engine, if_exists="replace", index=False,
                  schema="public", chunksize=5000)
    print(f"loaded {len(df):,} rows into {DB_NAME}.public.{TABLE}")

    # 2. get-or-create the dataset, refresh its column metadata
    table = (db.session.query(SqlaTable)
             .filter_by(table_name=TABLE, database_id=database.id).first())
    if not table:
        table = SqlaTable(table_name=TABLE, database=database, schema="public")
        db.session.add(table)
        db.session.flush()
    table.fetch_metadata()
    db.session.commit()
    print(f"dataset ready: id={table.id} cols={len(table.columns)}")

    # 3. numeric-diff gate: run each SIMPLE_AGG metric through Superset
    results = []
    for row in plan:
        if row["class"] != "SIMPLE_AGG" or not row["values"]:
            continue
        where = row.get("sql_where") or ""
        for v in row["values"]:
            qd = {
                "metrics": [{
                    "expressionType": "SIMPLE",
                    "column": {"column_name": v["column"]},
                    "aggregate": v["aggregate"],
                    "label": v["metric"],
                }],
                "columns": [], "groupby": [], "orderby": [],
                "is_timeseries": False, "filter": [],
                "extras": {"where": where},
                "from_dttm": None, "to_dttm": None,
                "granularity": None, "row_limit": 1,
            }
            try:
                got = float(table.query(qd).df.iloc[0, 0])
            except Exception as e:
                results.append((row["sheet"], v["metric"], v["expected"], None,
                                f"ERROR: {e}"))
                continue
            exp = v["expected"]
            rel = abs(got - exp) / (abs(exp) or 1)
            status = "PASS" if rel <= TOL else "FAIL"
            results.append((row["sheet"], v["metric"], exp, got, status))

    # 4. report
    print("\n=== NUMERIC-DIFF GATE (Superset query vs source ground truth) ===")
    print(f'{"sheet":<10} {"metric":<20} {"source":>14} {"superset":>14}  verdict')
    npass = 0
    for sheet, metric, exp, got, status in results:
        gots = f"{got:,.0f}" if isinstance(got, float) else "—"
        mark = "✅" if status == "PASS" else "❌"
        if status == "PASS":
            npass += 1
        print(f'{sheet:<10} {metric:<20} {exp:>14,.0f} {gots:>14}  {mark} {status}')
    print(f"\n{npass}/{len(results)} metrics MATCH exactly (within {TOL:.1%}).")
    json.dump(
        [{"sheet": s, "metric": m, "source": e, "superset": g, "status": st}
         for s, m, e, g, st in results],
        open("/tmp/fidelity_report.json", "w"), indent=2, default=str)
    print("wrote /tmp/fidelity_report.json")
