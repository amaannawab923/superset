"""Merchandise Sales -> Superset, faithfully: a tabbed dashboard mirroring the
3 Tableau tabs (Overview / Deep Exploration / Detail Transaction Records).
Overview tab is complete (incl. Top Products, customer review, most rating)."""
import json
import pandas as pd
from superset.app import create_app

DASH = "Merchandise Sales (migrated, tabbed)"
NOV = "ym = '2024-11'"
app = create_app()
with app.app_context():
    from superset import db
    from superset.connectors.sqla.models import SqlaTable
    from superset.models.slice import Slice
    from superset.models.dashboard import Dashboard

    df = pd.read_parquet("/tmp/merch_full.parquet")
    database = db.session.query(SqlaTable).filter_by(table_name="mig_orders").first().database
    with database.get_sqla_engine() as e:
        df.to_sql("mig_merch2", e, if_exists="replace", index=False, schema="public", chunksize=5000)
    t = db.session.query(SqlaTable).filter_by(table_name="mig_merch2", database_id=database.id).first()
    if not t:
        t = SqlaTable(table_name="mig_merch2", database=database, schema="public")
        db.session.add(t); db.session.flush()
    t.fetch_metadata(); db.session.commit()
    ds = f"{t.id}__table"

    def sm(col, agg="SUM", label=None):
        return {"expressionType": "SIMPLE", "column": {"column_name": col},
                "aggregate": agg, "label": label or f"{agg}({col})"}
    def wsql(x): return [{"clause": "WHERE", "expressionType": "SQL", "sqlExpression": x}]
    def mk(name, vt, p, dsid=None):
        db.session.query(Slice).filter_by(slice_name=name).delete(); db.session.flush()
        sl = Slice(slice_name=name, viz_type=vt, datasource_type="table",
                   datasource_id=dsid or t.id, params=json.dumps(p)); db.session.add(sl); db.session.flush()
        return sl.id
    import hashlib
    def vds(sql):
        nm = "vds_" + hashlib.md5(sql.encode()).hexdigest()[:10]
        v = db.session.query(SqlaTable).filter_by(table_name=nm, database_id=database.id).first()
        if not v:
            v = SqlaTable(table_name=nm, database=database); db.session.add(v)
        v.sql = sql; v.schema = None; db.session.flush(); v.fetch_metadata(); db.session.commit()
        return v
    C = {}

    # ---------- OVERVIEW tab ----------
    for lbl, cat in [("Clothing", "Clothing"), ("Ornaments", "Ornaments"), ("Other", "Other")]:
        C["kpi_" + cat] = mk(f"{lbl} (m2)", "big_number", {
            "datasource": ds, "viz_type": "big_number", "metric": sm("Revenue"),
            "adhoc_filters": wsql(f"\"Product Category\" = '{cat}'"),
            "granularity_sqla": "Order Date", "time_grain_sqla": "P1M",
            "compare_lag": "1", "compare_suffix": "vs Oct-24", "show_trend_line": True,
            "start_y_axis_at_zero": True, "subheader": lbl, "y_axis_format": "$,.0f"})
    C["top_products"] = mk("Top Products by Revenue (m2)", "echarts_timeseries_bar", {
        "datasource": ds, "viz_type": "echarts_timeseries_bar", "x_axis": "Product ID",
        "metrics": [sm("Revenue")], "adhoc_filters": wsql(NOV), "row_limit": 12,
        "x_axis_sort_by": "Revenue", "x_axis_sort_asc": False, "y_axis_format": "$,.0f"})
    C["map"] = mk("Sales by Location (m2)", "deck_scatter", {
        "datasource": ds, "viz_type": "deck_scatter",
        "spatial": {"latCol": "Latitude", "lonCol": "Longitude", "type": "latlong"},
        "adhoc_filters": wsql(NOV), "row_limit": 5000,
        "mapbox_style": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        "viewport": {"latitude": 25, "longitude": 5, "zoom": 1.3, "bearing": 0, "pitch": 0},
        "autozoom": True, "point_unit": "square_m",
        "point_radius_fixed": {"type": "metric", "value": sm("Revenue")},
        "min_radius": 3, "max_radius": 250, "multiplier": 10,
        "color_picker": {"r": 0, "g": 122, "b": 135, "a": 0.85}})
    C["genage"] = mk("Revenue by Gender & Age (m2)", "echarts_timeseries_bar", {
        "datasource": ds, "viz_type": "echarts_timeseries_bar", "x_axis": "Age Group",
        "groupby": ["Buyer Gender"], "metrics": [sm("Revenue")], "adhoc_filters": wsql(NOV),
        "x_axis_sort_asc": True, "y_axis_format": "$,.0f"})
    C["most_rating"] = mk("Rating Distribution (m2)", "echarts_timeseries_bar", {
        "datasource": ds, "viz_type": "echarts_timeseries_bar", "x_axis": "Rating",
        "metrics": [sm("Order ID", "COUNT", "reviews")], "adhoc_filters": wsql(NOV),
        "x_axis_sort_asc": True})
    C["review"] = mk("Customer Review (m2)", "big_number_total", {
        "datasource": ds, "viz_type": "big_number_total", "metric": sm("Rating", "AVG"),
        "adhoc_filters": wsql(NOV), "subheader": "Avg rating (Nov-24)", "y_axis_format": ".2f"})
    C["txn"] = mk("Transaction History (m2)", "table", {
        "datasource": ds, "viz_type": "table", "query_mode": "raw",
        "all_columns": ["Order ID", "Type", "Order Date", "Product Category", "Revenue", "Rating", "Satisfaction"],
        "order_by_cols": ['["Order Date", false]'], "adhoc_filters": wsql(NOV), "row_limit": 100})

    # ---------- DETAIL TRANSACTION RECORDS tab ----------
    C["txn_full"] = mk("All Transactions (m2)", "table", {
        "datasource": ds, "viz_type": "table", "query_mode": "raw",
        "all_columns": ["Order ID", "Order Date", "Product ID", "Product Category", "Type",
                        "Buyer Gender", "Order Location", "Quantity", "Revenue", "Rating", "Satisfaction"],
        "order_by_cols": ['["Order Date", false]'], "row_limit": 1000})

    # ---------- DEEP EXPLORATION tab (faithful to the Tableau tab) ----------
    C["all_products"] = mk("All Products (m2)", "big_number_total", {
        "datasource": ds, "viz_type": "big_number_total", "metric": sm("Revenue"),
        "adhoc_filters": wsql(NOV), "subheader": "All products (Nov-24)", "y_axis_format": "$,.0f"})
    C["review_all"] = mk("Customer Review — all time (m2)", "big_number_total", {
        "datasource": ds, "viz_type": "big_number_total", "metric": sm("Rating", "AVG"),
        "subheader": "Avg rating (all time)", "y_axis_format": ".2f"})
    # Pie: Sales by International Shipping (Domestic vs International)  [was missing]
    C["ship_pie"] = mk("Sales by International Shipping (m2)", "pie", {
        "datasource": ds, "viz_type": "pie", "groupby": ["Type"], "metric": sm("Revenue"),
        "donut": True, "innerRadius": 45, "show_labels": True, "label_type": "key_value"})
    # Pareto: products by revenue (bar) + cumulative % (line)  [was missing]
    pv = vds('SELECT "Product ID" AS product, SUM("Revenue") AS revenue, '
             'round(SUM(SUM("Revenue")) OVER (ORDER BY SUM("Revenue") DESC) '
             '/ SUM(SUM("Revenue")) OVER () * 100, 1) AS cum_pct '
             'FROM public.mig_merch2 GROUP BY 1')
    C["pareto"] = mk("Pareto — Products by Revenue (m2)", "mixed_timeseries", {
        "datasource": f"{pv.id}__table", "viz_type": "mixed_timeseries", "x_axis": "product",
        "metrics": [{"expressionType": "SQL", "sqlExpression": "MAX(revenue)", "label": "Revenue"}],
        "metrics_b": [{"expressionType": "SQL", "sqlExpression": "MAX(cum_pct)", "label": "Cumulative %"}],
        "x_axis_sort_by": "Revenue", "x_axis_sort_asc": False, "row_limit": 50,
        "y_axis_format": "$,.0f", "y_axis_format_secondary": ".0f",
        "seriesType": "bar", "seriesTypeB": "line"}, dsid=pv.id)
    # Bar: Revenue by Category  [renamed from "Categories Performance"]
    C["categories"] = mk("Revenue by Category (m2)", "echarts_timeseries_bar", {
        "datasource": ds, "viz_type": "echarts_timeseries_bar", "x_axis": "Product Category",
        "metrics": [sm("Revenue")], "row_limit": 25, "x_axis_sort_by": "Revenue",
        "x_axis_sort_asc": False, "y_axis_format": "$,.0f"})
    # Bar: Top 10 Locations by Revenue
    C["top10_loc"] = mk("Top 10 Locations (m2)", "echarts_timeseries_bar", {
        "datasource": ds, "viz_type": "echarts_timeseries_bar", "x_axis": "Order Location",
        "metrics": [sm("Revenue")], "row_limit": 10, "x_axis_sort_by": "Revenue",
        "x_axis_sort_asc": False, "y_axis_format": "$,.0f"})
    # Line: Weekly Revenue Trend  [fixed grain=week (string x, no time-axis crash)]
    C["weekly_trend"] = mk("Weekly Revenue Trend (m2)", "echarts_timeseries_line", {
        "datasource": ds, "viz_type": "echarts_timeseries_line", "x_axis": "week",
        "metrics": [sm("Revenue")], "y_axis_format": "$,.0f", "x_axis_sort_asc": True})
    # Bar grouped by GENDER: Age Buyer Distribution  [fixed: add gender series]
    C["age_gender"] = mk("Age Buyer Distribution by Gender (m2)", "echarts_timeseries_bar", {
        "datasource": ds, "viz_type": "echarts_timeseries_bar", "x_axis": "Age Group",
        "groupby": ["Buyer Gender"], "metrics": [sm("Revenue")], "x_axis_sort_asc": True,
        "y_axis_format": "$,.0f"})
    # Bar: Rating distribution
    C["rating_dist"] = mk("Rating Distribution — deep (m2)", "echarts_timeseries_bar", {
        "datasource": ds, "viz_type": "echarts_timeseries_bar", "x_axis": "Rating",
        "metrics": [sm("Order ID", "COUNT", "reviews")], "x_axis_sort_asc": True})
    # Line: Shipping Charge Trend by shipping type
    C["ship_trend"] = mk("Shipping Charge Trend (m2)", "echarts_timeseries_line", {
        "datasource": ds, "viz_type": "echarts_timeseries_line", "x_axis": "week",
        "groupby": ["Type"], "metrics": [sm("Shipping Charges")], "x_axis_sort_asc": True,
        "y_axis_format": "$,.2f"})
    db.session.commit()
    print("charts:", len(C))

    # ---------- tabbed layout ----------
    TABS = "TABS-1"
    pos = {"DASHBOARD_VERSION_KEY": "v2",
           "ROOT_ID": {"type": "ROOT", "id": "ROOT_ID", "children": ["GRID_ID"]},
           "GRID_ID": {"type": "GRID", "id": "GRID_ID", "parents": ["ROOT_ID"], "children": [TABS]},
           "HEADER_ID": {"type": "HEADER", "id": "HEADER_ID", "meta": {"text": "Merchandise Sales"}},
           TABS: {"type": "TABS", "id": TABS, "parents": ["ROOT_ID", "GRID_ID"], "children": [], "meta": {}}}
    tabs = {
        "Overview": [
            [(C["kpi_Clothing"], "Clothing", 4, 40), (C["kpi_Ornaments"], "Ornaments", 4, 40),
             (C["kpi_Other"], "Other", 4, 40)],
            [(C["top_products"], "Top Products by Revenue", 6, 55), (C["map"], "Sales by Location", 6, 55)],
            [(C["genage"], "Revenue by Gender & Age", 6, 50), (C["most_rating"], "Rating Distribution", 3, 50),
             (C["review"], "Customer Review", 3, 50)],
            [(C["txn"], "Transaction History", 12, 45)],
        ],
        "Deep Exploration": [
            [(C["all_products"], "All Products", 3, 28), (C["review_all"], "Customer Review", 3, 28),
             (C["ship_pie"], "Sales by International Shipping", 6, 50)],
            [(C["pareto"], "Pareto — Products by Revenue", 12, 55)],
            [(C["categories"], "Revenue by Category", 4, 50), (C["top10_loc"], "Top 10 Locations", 8, 50)],
            [(C["weekly_trend"], "Weekly Revenue Trend", 12, 45)],
            [(C["age_gender"], "Age Buyer Distribution by Gender", 6, 50),
             (C["rating_dist"], "Rating Distribution", 6, 50)],
            [(C["ship_trend"], "Shipping Charge Trend", 12, 45)],
        ],
        "Detail Transaction Records": [
            [(C["txn_full"], "All Transactions", 12, 70)],
        ],
    }
    for ti, (tab_name, rows) in enumerate(tabs.items()):
        tabid = f"TAB-{ti}"
        pos[TABS]["children"].append(tabid)
        pos[tabid] = {"type": "TAB", "id": tabid, "parents": ["ROOT_ID", "GRID_ID", TABS],
                      "children": [], "meta": {"text": tab_name}}
        for ri, row in enumerate(rows):
            rid = f"ROW-{ti}-{ri}"
            pos[tabid]["children"].append(rid)
            pos[rid] = {"type": "ROW", "id": rid, "children": [],
                        "parents": ["ROOT_ID", "GRID_ID", TABS, tabid],
                        "meta": {"background": "BACKGROUND_TRANSPARENT"}}
            for cid, nm, w, h in row:
                k = f"CHART-{cid}"
                pos[rid]["children"].append(k)
                pos[k] = {"type": "CHART", "id": k, "children": [],
                          "parents": ["ROOT_ID", "GRID_ID", TABS, tabid, rid],
                          "meta": {"chartId": cid, "width": w, "height": h, "sliceName": nm}}

    db.session.query(Dashboard).filter_by(dashboard_title=DASH).delete(); db.session.commit()
    ids = list(C.values())
    d = Dashboard(dashboard_title=DASH, slug="merch-tabbed", position_json=json.dumps(pos),
                  published=True, slices=[db.session.query(Slice).get(c) for c in ids])
    db.session.add(d); db.session.commit()
    print(f"DASHBOARD id={d.id} '{DASH}' — 3 tabs, {len(ids)} charts")
    print(f"open: http://localhost:8088/superset/dashboard/{d.id}/")
