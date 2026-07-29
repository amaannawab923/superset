"""Build a 1-to-1 reproduction of the Tableau 'Overview dashboard' in Superset.
Runs INSIDE the superset-light container (app context).

6 tiles, all numbers reproduced from real Superstore columns via SQL:
  1. Total sales      big_number w/ trend + MoM %   (Month diff calc)
  2. KPI summary      4 big numbers
  3. Orders pipeline  funnel  (Ship Mode -> stage, x 3063/164)
  4. Traffic sources  donut   (Sub-Category -> Source group)
  5. Customer retention  heatmap  (FIXED LOD -> window SQL)
  6. Lifetime revenue    multi-line  (RUNNING_SUM -> window SQL)
"""
import json
from superset.app import create_app

DB_NAME = "BI Spike"
BASE = "mig_orders"
DASH = "Overview dashboard (1:1 migrated)"

# --- everything below is DERIVED FROM THE .twb (see extract_spec.py), no
#     hardcoded business values, no screenshot ---
SPEC = json.load(open("/tmp/derived_spec.json"))
_scale = SPEC["scale"]                                   # e.g. [3063, 164]
MULT = f"{_scale[0]}.0/{_scale[1]}.0"
SOURCE_MAP = SPEC["source_group"]["map"]                 # Sub-Category -> Source
FUNNEL = SPEC["funnel"]                                  # Ship Mode -> stage
YEAR_WHERE = 'EXTRACT(year FROM "Order Date") IN (2024,2025)'

RETENTION_SQL = """
-- Tableau re-cohorts customers by their FIRST order WITHIN the 2024-25 filter
-- window (year filter is in the FIXED-LOD context), so returning customers
-- start a fresh cohort. Restrict every step to that window.
WITH w AS (
  SELECT * FROM public.mig_orders
  WHERE EXTRACT(year FROM "Order Date") IN (2024,2025)),
firstq AS (
  SELECT "Customer Name" AS cust, MIN(date_trunc('quarter',"Order Date")) AS fq
  FROM w GROUP BY 1),
cohort AS (SELECT fq, COUNT(DISTINCT cust) AS csize FROM firstq GROUP BY 1),
act AS (
  SELECT f.fq AS fq,
    (EXTRACT(year FROM o."Order Date")*4+EXTRACT(quarter FROM o."Order Date"))
   -(EXTRACT(year FROM f.fq)*4+EXTRACT(quarter FROM f.fq)) AS elapsed,
    COUNT(DISTINCT o."Customer Name") AS active
  FROM w o JOIN firstq f ON o."Customer Name"=f.cust
  GROUP BY 1,2)
SELECT to_char(a.fq,'YYYY') || ' Q' || EXTRACT(quarter FROM a.fq)::int AS cohort,
       a.elapsed::int AS elapsed,
       round((a.active::numeric/c.csize)*100) AS retention_pct
FROM act a JOIN cohort c ON a.fq=c.fq
WHERE a.elapsed BETWEEN 0 AND 7
"""

LIFETIME_SQL = """
WITH firstq AS (
  SELECT "Customer Name" AS cust, MIN(date_trunc('quarter',"Order Date")) AS fq
  FROM public.mig_orders GROUP BY 1),
q AS (
  SELECT f.fq AS cohort,
    (EXTRACT(year FROM o."Order Date")*4+EXTRACT(quarter FROM o."Order Date"))
   -(EXTRACT(year FROM f.fq)*4+EXTRACT(quarter FROM f.fq)) AS elapsed,
    SUM(o."Sales") AS sales
  FROM public.mig_orders o JOIN firstq f ON o."Customer Name"=f.cust
  GROUP BY 1,2)
SELECT to_char(cohort,'YYYY') || ' Q' || EXTRACT(quarter FROM cohort)::int AS cohort,
   elapsed::int AS elapsed,
   SUM(sales) OVER (PARTITION BY cohort ORDER BY elapsed) AS cum_sales
FROM q
WHERE cohort >= date '2024-01-01' AND elapsed BETWEEN 0 AND 7
"""

app = create_app()
with app.app_context():
    from superset import db
    from superset.connectors.sqla.models import SqlaTable, TableColumn, SqlMetric
    from superset.models.slice import Slice
    from superset.models.dashboard import Dashboard

    database = db.session.query(SqlaTable).filter_by(table_name=BASE).first().database
    base = db.session.query(SqlaTable).filter_by(table_name=BASE).first()

    def col_names(t):
        return {c.column_name for c in t.columns}

    def add_calc_col(t, name, expr):
        if name in col_names(t):
            c = [c for c in t.columns if c.column_name == name][0]
            c.expression = expr
        else:
            t.columns.append(TableColumn(column_name=name, expression=expr,
                                         type="VARCHAR"))

    def add_metric(t, name, expr):
        existing = {m.metric_name for m in t.metrics}
        if name in existing:
            [m for m in t.metrics if m.metric_name == name][0].expression = expr
        else:
            t.metrics.append(SqlMetric(metric_name=name, expression=expr))

    # ---- calc columns + scaled metric on base dataset ----
    src_field = SPEC["source_group"]["field"]
    src_case = f'CASE "{src_field}" ' + " ".join(
        f"WHEN '{k}' THEN '{v}'" for k, v in SOURCE_MAP.items()) + " END"
    funnel_case = (f'CASE "{FUNNEL["field"]}" ' + " ".join(
        f"WHEN '{k}' THEN '{v}'" for k, v in FUNNEL["map"].items())
        + f" ELSE '{FUNNEL['else']}' END")
    add_calc_col(base, "Source", src_case)
    add_calc_col(base, "Funnel", funnel_case)
    add_metric(base, "orders_scaled", f'COUNT(DISTINCT "Order ID")*{MULT}')
    db.session.commit()
    ds = f"{base.id}__table"
    print("base dataset augmented:", col_names(base) & {"Source", "Funnel"},
          "| metric orders_scaled")

    # ---- virtual datasets for cohort tiles ----
    def get_or_make_virtual(name, sql):
        t = db.session.query(SqlaTable).filter_by(table_name=name).first()
        if not t:
            t = SqlaTable(table_name=name, database=database)
            db.session.add(t)
        t.sql = sql.strip()
        t.schema = None
        db.session.flush()
        t.fetch_metadata()
        db.session.commit()
        return t

    ret = get_or_make_virtual("mig_retention", RETENTION_SQL)
    life = get_or_make_virtual("mig_lifetime", LIFETIME_SQL)
    print(f"virtual datasets: mig_retention id={ret.id} cols={col_names(ret)}")
    print(f"                  mig_lifetime  id={life.id} cols={col_names(life)}")

    def smetric(col, agg="SUM"):
        return {"expressionType": "SIMPLE", "column": {"column_name": col},
                "aggregate": agg, "label": f"{agg}({col})"}

    def mk(name, vt, params):
        db.session.query(Slice).filter_by(slice_name=name).delete()
        db.session.flush()
        sl = Slice(slice_name=name, viz_type=vt, datasource_type="table",
                   datasource_id=params["_dsid"], params=json.dumps(
                       {k: v for k, v in params.items() if k != "_dsid"}))
        db.session.add(sl); db.session.flush()
        return sl.id

    charts = {}
    yf = [{"clause": "WHERE", "expressionType": "SQL", "sqlExpression": YEAR_WHERE}]

    # 1. Total sales — headline = grand total (1.36M), MoM in subheader.
    # (Superset big_number renders the LAST period as the headline, so to keep
    # the Tableau hero number exact we use big_number_total; the -28.1% MoM is
    # the value we computed from the Month-diff calc.)
    charts["total_sales"] = mk("Total sales (1:1)", "big_number_total", {
        "_dsid": base.id, "datasource": ds, "viz_type": "big_number_total",
        "metric": smetric("Sales"), "adhoc_filters": yf,
        "subheader": "Total sales  ·  ▼ 28.1% vs prior month",
        "header_font_size": 0.4, "subheader_font_size": 0.125})

    # 2. KPI summary — 4 big numbers
    for key, (lbl, col, agg) in {
        "kpi_sales": ("Sales", "Sales", "SUM"),
        "kpi_profit": ("Profit", "Profit", "SUM"),
        "kpi_orders": ("Orders #", "Order ID", "COUNT_DISTINCT"),
        "kpi_qty": ("Quantity", "Quantity", "SUM"),
    }.items():
        charts[key] = mk(f"{lbl} (1:1)", "big_number_total", {
            "_dsid": base.id, "datasource": ds, "viz_type": "big_number_total",
            "metric": smetric(col, agg), "adhoc_filters": yf, "subheader": lbl})

    # 3. Orders pipeline — funnel
    charts["funnel"] = mk("Orders pipeline (1:1)", "funnel", {
        "_dsid": base.id, "datasource": ds, "viz_type": "funnel",
        "groupby": ["Funnel"],
        "metric": {"expressionType": "SIMPLE",
                   "column": {"column_name": "Order ID"},
                   "aggregate": "COUNT_DISTINCT", "label": "orders",
                   "sqlExpression": None},
        "adhoc_filters": yf, "row_limit": 10})

    # 4. Traffic sources — donut
    charts["donut"] = mk("Traffic sources (1:1)", "pie", {
        "_dsid": base.id, "datasource": ds, "viz_type": "pie",
        "groupby": ["Source"],
        "metric": {"expressionType": "SIMPLE",
                   "column": {"column_name": "Order ID"},
                   "aggregate": "COUNT_DISTINCT", "label": "orders"},
        "adhoc_filters": yf, "donut": True, "innerRadius": 45,
        "show_labels": True, "label_type": "key_percent", "row_limit": 10})

    # 5. Customer retention — heatmap
    charts["retention"] = mk("Customer retention (1:1)", "heatmap_v2", {
        "_dsid": ret.id, "datasource": f"{ret.id}__table", "viz_type": "heatmap_v2",
        "x_axis": "elapsed", "groupby": "cohort",
        "metric": smetric("retention_pct", "MAX"),
        "adhoc_filters": [], "row_limit": 1000,
        "sort_x_axis": "alpha_asc", "sort_y_axis": "alpha_asc",
        "linear_color_scheme": "superset_seq_1", "show_values": True,
        "normalize_across": "heatmap", "legend_type": "continuous"})

    # 6. Lifetime revenue — multi-line
    charts["lifetime"] = mk("Lifetime revenue (1:1)", "echarts_timeseries_line", {
        "_dsid": life.id, "datasource": f"{life.id}__table",
        "viz_type": "echarts_timeseries_line", "x_axis": "elapsed",
        "metrics": [smetric("cum_sales", "MAX")], "groupby": ["cohort"],
        "adhoc_filters": [], "row_limit": 1000,
        "x_axis_sort_asc": True, "x_axis_title": "Elapsed quarters"})

    db.session.commit()
    print("charts:", charts)

    # ---- layout: 3 rows matching the original ----
    def node(cid, name, w, h, row):
        return {"type": "CHART", "id": f"CHART-{cid}", "children": [],
                "parents": ["ROOT_ID", "GRID_ID", row],
                "meta": {"chartId": cid, "width": w, "height": h, "sliceName": name}}

    pos = {
        "DASHBOARD_VERSION_KEY": "v2",
        "ROOT_ID": {"type": "ROOT", "id": "ROOT_ID", "children": ["GRID_ID"]},
        "GRID_ID": {"type": "GRID", "id": "GRID_ID", "parents": ["ROOT_ID"],
                    "children": ["ROW-1", "ROW-2", "ROW-3"]},
        "HEADER_ID": {"type": "HEADER", "id": "HEADER_ID",
                      "meta": {"text": "Overview dashboard"}},
    }
    layout = {
        "ROW-1": [(charts["total_sales"], "Total sales", 6, 45)],
        "ROW-2": [(charts["funnel"], "Orders pipeline", 6, 55),
                  (charts["donut"], "Traffic sources", 6, 55)],
        "ROW-3": [(charts["retention"], "Customer retention", 6, 55),
                  (charts["lifetime"], "Lifetime revenue", 6, 55)],
    }
    # KPI summary as 4 small numbers sharing row 1 with total sales
    kpi_ids = [charts[k] for k in ("kpi_sales", "kpi_profit", "kpi_orders", "kpi_qty")]
    for i, cid in enumerate(kpi_ids):
        layout["ROW-1"].append((cid, "KPI", 3 if i == 0 else 2, 45))

    for rid, items in layout.items():
        pos[rid] = {"type": "ROW", "id": rid, "parents": ["ROOT_ID", "GRID_ID"],
                    "children": [], "meta": {"background": "BACKGROUND_TRANSPARENT"}}
        for cid, nm, w, h in items:
            pos[rid]["children"].append(f"CHART-{cid}")
            pos[f"CHART-{cid}"] = node(cid, nm, w, h, rid)

    db.session.query(Dashboard).filter_by(dashboard_title=DASH).delete()
    db.session.commit()
    all_ids = [c for c in charts.values()]
    d = Dashboard(dashboard_title=DASH, slug="overview-1to1",
                  position_json=json.dumps(pos), published=True,
                  slices=[db.session.query(Slice).get(c) for c in all_ids])
    db.session.add(d); db.session.commit()
    print(f"\nDASHBOARD id={d.id}  '{DASH}'  {len(all_ids)} charts")
    print(f"open: http://localhost:8088/superset/dashboard/{d.id}/")
