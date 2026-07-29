"""Build the migrated Merchandise Sales Overview dashboard in Superset.
Runs INSIDE the superset-light container (app context)."""
import json
import pandas as pd
from superset.app import create_app

DB_NAME = "BI Spike"
TABLE = "mig_merch"
DASH = "Merchandise Sales Overview (migrated)"
YM = "ym = '2024-11'"

app = create_app()
with app.app_context():
    from superset import db
    from superset.connectors.sqla.models import SqlaTable
    from superset.models.slice import Slice
    from superset.models.dashboard import Dashboard

    params = json.load(open("/tmp/merch_params.json"))
    df = pd.read_parquet("/tmp/merch.parquet")
    database = db.session.query(SqlaTable).filter_by(table_name="mig_orders").first()
    database = database.database if database else \
        db.session.query(__import__("superset.models.core", fromlist=["Database"]).Database
                         ).filter_by(database_name=DB_NAME).first()

    with database.get_sqla_engine() as e:
        df.to_sql(TABLE, e, if_exists="replace", index=False, schema="public", chunksize=5000)
    print(f"loaded {len(df):,} rows -> {TABLE}")

    t = db.session.query(SqlaTable).filter_by(table_name=TABLE, database_id=database.id).first()
    if not t:
        t = SqlaTable(table_name=TABLE, database=database, schema="public")
        db.session.add(t); db.session.flush()
    t.fetch_metadata(); db.session.commit()
    ds = f"{t.id}__table"

    def smetric(col, agg="SUM", label=None):
        return {"expressionType": "SIMPLE", "column": {"column_name": col},
                "aggregate": agg, "label": label or f"{agg}({col})"}

    def mk(name, vt, p):
        db.session.query(Slice).filter_by(slice_name=name).delete(); db.session.flush()
        sl = Slice(slice_name=name, viz_type=vt, datasource_type="table",
                   datasource_id=t.id, params=json.dumps(p))
        db.session.add(sl); db.session.flush()
        return sl.id

    def wsql(expr):
        return [{"clause": "WHERE", "expressionType": "SQL", "sqlExpression": expr}]

    charts = {}
    # ---- KPI cards: big_number w/ 12-month sparkline + MoM (value = last month
    #      = Nov-24, so the headline is the $ figure, exactly like the source card) ----
    kmap = [("Clothing", "Clothing", "Clothing"),
            ("Ornaments", "Ornaments", "Ornaments"), ("Other", "Other", "Other")]
    for label, key, cat in kmap:
        catf = [] if cat is None else wsql(f"\"Product Category\" = '{cat}'")
        charts["kpi_" + key] = mk(f"{label} (merch)", "big_number", {
            "datasource": ds, "viz_type": "big_number",
            "metric": smetric("Revenue"), "adhoc_filters": catf,
            "granularity_sqla": "Order Date", "time_grain_sqla": "P1M",
            "compare_lag": "1", "compare_suffix": "vs Oct-24",
            "show_trend_line": True, "start_y_axis_at_zero": True,
            "subheader": label, "y_axis_format": "$,.0f",
            "header_font_size": 0.3, "subheader_font_size": 0.125})

    # ---- Revenue by Gender & Age Group (grouped bar) ----
    charts["genage"] = mk("Revenue by Gender & Age Group (merch)", "echarts_timeseries_bar", {
        "datasource": ds, "viz_type": "echarts_timeseries_bar",
        "x_axis": "Age Group", "groupby": ["Buyer Gender"],
        "metrics": [smetric("Revenue")], "adhoc_filters": wsql(YM),
        "row_limit": 100, "x_axis_sort_asc": True, "y_axis_format": "$,.0f",
        "x_axis_title": "Age Group"})

    # ---- Revenue by Location (deck.gl scatter map on OpenStreetMap tiles) ----
    charts["location"] = mk("Revenue by Location (merch)", "deck_scatter", {
        "datasource": ds, "viz_type": "deck_scatter",
        "spatial": {"latCol": "Latitude", "lonCol": "Longitude", "type": "latlong"},
        "adhoc_filters": wsql(YM), "row_limit": 5000,
        "mapbox_style": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        "viewport": {"latitude": 25, "longitude": 5, "zoom": 1.3,
                     "bearing": 0, "pitch": 0},
        "autozoom": True, "point_unit": "square_m",
        "point_radius_fixed": {"type": "metric",
                               "value": {"expressionType": "SIMPLE",
                                         "column": {"column_name": "Revenue"},
                                         "aggregate": "SUM", "label": "SUM(Revenue)"}},
        "min_radius": 3, "max_radius": 250, "multiplier": 10,
        "color_picker": {"r": 0, "g": 122, "b": 135, "a": 0.85}})

    # ---- Transaction History (table) ----
    charts["txn"] = mk("Transaction History (merch)", "table", {
        "datasource": ds, "viz_type": "table", "query_mode": "raw",
        "all_columns": ["Order ID", "Type", "Order Date", "Revenue", "Satisfaction"],
        "order_by_cols": ['["Order Date", false]'],
        "adhoc_filters": wsql(YM), "row_limit": 100,
        "column_config": {"Revenue": {"d3NumberFormat": "$,.0f"}}})

    db.session.commit()
    print("charts:", charts)

    # ---- layout ----
    def node(cid, nm, w, h, row):
        return {"type": "CHART", "id": f"CHART-{cid}", "children": [],
                "parents": ["ROOT_ID", "GRID_ID", row],
                "meta": {"chartId": cid, "width": w, "height": h, "sliceName": nm}}
    pos = {"DASHBOARD_VERSION_KEY": "v2",
           "ROOT_ID": {"type": "ROOT", "id": "ROOT_ID", "children": ["GRID_ID"]},
           "GRID_ID": {"type": "GRID", "id": "GRID_ID", "parents": ["ROOT_ID"],
                       "children": ["ROW-1", "ROW-2", "ROW-3"]},
           "HEADER_ID": {"type": "HEADER", "id": "HEADER_ID",
                         "meta": {"text": "Merchandise Sales Overview"}}}
    layout = {
        "ROW-1": [(charts["kpi_Clothing"], "Clothing", 4, 45),
                  (charts["kpi_Ornaments"], "Ornaments", 4, 45),
                  (charts["kpi_Other"], "Other", 4, 45)],
        "ROW-2": [(charts["location"], "Revenue by Location", 6, 55),
                  (charts["genage"], "Revenue by Gender & Age", 6, 55)],
        "ROW-3": [(charts["txn"], "Transaction History", 12, 50)],
    }
    for rid, items in layout.items():
        pos[rid] = {"type": "ROW", "id": rid, "parents": ["ROOT_ID", "GRID_ID"],
                    "children": [], "meta": {"background": "BACKGROUND_TRANSPARENT"}}
        for cid, nm, w, h in items:
            pos[rid]["children"].append(f"CHART-{cid}")
            pos[f"CHART-{cid}"] = node(cid, nm, w, h, rid)

    db.session.query(Dashboard).filter_by(dashboard_title=DASH).delete(); db.session.commit()
    ids = list(charts.values())
    d = Dashboard(dashboard_title=DASH, slug="merch-migrated",
                  position_json=json.dumps(pos), published=True,
                  slices=[db.session.query(Slice).get(c) for c in ids])
    db.session.add(d); db.session.commit()
    print(f"DASHBOARD id={d.id} '{DASH}' with {len(ids)} charts")
    print(f"open: http://localhost:8088/superset/dashboard/{d.id}/")
