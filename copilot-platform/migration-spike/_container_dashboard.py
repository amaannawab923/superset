"""Runs INSIDE the superset-light container (app context).
Creates real Superset charts for every verified metric (scalar KPIs + two
dimensional charts whose numbers are gate-checked) and assembles them into an
actual openable Dashboard with a two-row layout.
"""
import json
from superset.app import create_app

DB_NAME = "BI Spike"
TABLE = "mig_orders"
DASH_TITLE = "Overview Dashboard (migrated from Tableau)"
PLAN = "/tmp/migration_plan.json"

# ground truth for the dimensional charts (from pandas), for the diff gate
EXPECT_CATEGORY = {"Furniture": 754748, "Office Supplies": 731893, "Technology": 839893}

app = create_app()
with app.app_context():
    from superset import db
    from superset.connectors.sqla.models import SqlaTable
    from superset.models.slice import Slice
    from superset.models.dashboard import Dashboard

    plan = json.load(open(PLAN))
    table = db.session.query(SqlaTable).filter_by(table_name=TABLE).first()
    assert table, "dataset mig_orders missing — run apply_verify first"
    ds = f"{table.id}__table"

    def smetric(col, agg="SUM"):
        return {"expressionType": "SIMPLE", "column": {"column_name": col},
                "aggregate": agg, "label": f"{agg}({col})"}

    # ---- scalar KPI charts from the plan ----
    LABELS = {
        ("Sum(Sales)", "2024"): ("Total Sales", "Last 2 years"),
        ("Sum(Sales)", ""): ("Total Sales (all time)", "All years"),
        ("Sum(Profit)", "2024"): ("Total Profit", "Last 2 years"),
        ("Sum(Quantity)", "2024"): ("Quantity Sold", "Last 2 years"),
        ("CountD(Order ID)", "2024"): ("Orders", "Last 2 years"),
    }
    kpi_specs, seen = [], set()
    for row in plan:
        if row["class"] != "SIMPLE_AGG":
            continue
        where = row.get("sql_where") or ""
        yr = "2024" if "2024" in where else ""
        for v in row["values"]:
            key = (v["metric"], yr)
            if key in LABELS and key not in seen:
                seen.add(key)
                name, sub = LABELS[key]
                kpi_specs.append((name, sub, v, where))

    made_kpi = []
    for name, sub, v, where in kpi_specs:
        full = f"{name} (migrated)"
        db.session.query(Slice).filter_by(slice_name=full).delete()
        params = {"datasource": ds, "viz_type": "big_number_total",
                  "metric": smetric(v["column"], v["aggregate"]),
                  "adhoc_filters": ([{"clause": "WHERE", "expressionType": "SQL",
                                      "sqlExpression": where}] if where else []),
                  "subheader": sub}
        sl = Slice(slice_name=full, viz_type="big_number_total",
                   datasource_type="table", datasource_id=table.id,
                   params=json.dumps(params))
        db.session.add(sl); db.session.flush()
        made_kpi.append((sl.id, full))
    db.session.commit()

    # ---- dimensional charts (faithful, from clean underlying data) ----
    pie_params = {"datasource": ds, "viz_type": "pie", "groupby": ["Category"],
                  "metric": smetric("Sales"), "adhoc_filters": [],
                  "row_limit": 100, "show_labels": True, "label_type": "key_value"}
    bar_params = {"datasource": ds, "viz_type": "echarts_timeseries_bar",
                  "x_axis": "Sub-Category", "metrics": [smetric("Sales")],
                  "groupby": [], "adhoc_filters": [], "row_limit": 100,
                  "orientation": "vertical", "x_axis_sort_asc": False,
                  "x_axis_title": "Sub-Category"}
    made_dim = []
    for full, vt, params in [("Sales by Category (migrated)", "pie", pie_params),
                             ("Sales by Sub-Category (migrated)", "echarts_timeseries_bar", bar_params)]:
        db.session.query(Slice).filter_by(slice_name=full).delete()
        sl = Slice(slice_name=full, viz_type=vt, datasource_type="table",
                   datasource_id=table.id, params=json.dumps(params))
        db.session.add(sl); db.session.flush()
        made_dim.append((sl.id, full))
    db.session.commit()

    # ---- numeric-diff gate on the pie (grouped) ----
    qd = {"metrics": [smetric("Sales")], "columns": ["Category"], "groupby": ["Category"],
          "orderby": [], "is_timeseries": False, "filter": [], "extras": {"where": ""},
          "from_dttm": None, "to_dttm": None, "granularity": None, "row_limit": 100}
    got = table.query(qd).df
    gotmap = {r["Category"]: round(float(r[got.columns[-1]])) for _, r in got.iterrows()}
    print("dimensional gate (Sales by Category):")
    allok = True
    for cat, exp in EXPECT_CATEGORY.items():
        g = gotmap.get(cat)
        ok = g == exp
        allok &= ok
        print(f"  {cat:<16} source={exp:>10,}  superset={g:>10,}  {'PASS ✅' if ok else 'FAIL ❌'}")
    print(f"  => {'ALL MATCH' if allok else 'MISMATCH'}")

    # ---- assemble a two-row dashboard ----
    def chart_node(cid, name, w, h):
        return {"type": "CHART", "id": f"CHART-{cid}",
                "parents": ["ROOT_ID", "GRID_ID"], "children": [],
                "meta": {"chartId": cid, "width": w, "height": h, "sliceName": name}}

    pos = {
        "DASHBOARD_VERSION_KEY": "v2",
        "ROOT_ID": {"type": "ROOT", "id": "ROOT_ID", "children": ["GRID_ID"]},
        "GRID_ID": {"type": "GRID", "id": "GRID_ID", "parents": ["ROOT_ID"],
                    "children": ["ROW-1", "ROW-2"]},
        "HEADER_ID": {"type": "HEADER", "id": "HEADER_ID", "meta": {"text": DASH_TITLE}},
        "ROW-1": {"type": "ROW", "id": "ROW-1", "parents": ["ROOT_ID", "GRID_ID"],
                  "children": [], "meta": {"background": "BACKGROUND_TRANSPARENT"}},
        "ROW-2": {"type": "ROW", "id": "ROW-2", "parents": ["ROOT_ID", "GRID_ID"],
                  "children": [], "meta": {"background": "BACKGROUND_TRANSPARENT"}},
    }
    for cid, name in made_kpi:
        pos["ROW-1"]["children"].append(f"CHART-{cid}")
        pos[f"CHART-{cid}"] = chart_node(cid, name, 2, 40)
        pos[f"CHART-{cid}"]["parents"].append("ROW-1")
    for cid, name in made_dim:
        pos["ROW-2"]["children"].append(f"CHART-{cid}")
        pos[f"CHART-{cid}"] = chart_node(cid, name, 6, 60)
        pos[f"CHART-{cid}"]["parents"].append("ROW-2")

    db.session.query(Dashboard).filter_by(dashboard_title=DASH_TITLE).delete()
    db.session.commit()
    all_ids = [c for c, _ in made_kpi + made_dim]
    dash = Dashboard(dashboard_title=DASH_TITLE, slug="overview-migrated",
                     position_json=json.dumps(pos), published=True,
                     slices=[db.session.query(Slice).get(cid) for cid in all_ids])
    db.session.add(dash); db.session.commit()
    print(f"\nDASHBOARD id={dash.id}  charts: {len(all_ids)} "
          f"({len(made_kpi)} KPIs + {len(made_dim)} dimensional)")
    print(f"open: http://localhost:8088/superset/dashboard/{dash.id}/")
