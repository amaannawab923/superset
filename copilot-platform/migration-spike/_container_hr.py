"""HR Attrition dashboard -> Superset (agent-generated build)."""
import json
import pandas as pd
from superset.app import create_app

DASH = "HR Analytics Dashboard (migrated)"
app = create_app()
with app.app_context():
    from superset import db
    from superset.connectors.sqla.models import SqlaTable
    from superset.models.slice import Slice
    from superset.models.dashboard import Dashboard

    df = pd.read_parquet("/tmp/hr.parquet")
    database = db.session.query(SqlaTable).filter_by(table_name="mig_orders").first().database
    with database.get_sqla_engine() as e:
        df.to_sql("hr_emp", e, if_exists="replace", index=False, schema="public")
    t = db.session.query(SqlaTable).filter_by(table_name="hr_emp", database_id=database.id).first()
    if not t:
        t = SqlaTable(table_name="hr_emp", database=database, schema="public")
        db.session.add(t); db.session.flush()
    t.fetch_metadata(); db.session.commit()
    ds = f"{t.id}__table"

    def m_simple(col, agg="SUM", label=None):
        return {"expressionType": "SIMPLE", "column": {"column_name": col},
                "aggregate": agg, "label": label or f"{agg}({col})"}

    def m_sql(sql, label):
        return {"expressionType": "SQL", "sqlExpression": sql, "label": label}

    def mk(name, vt, p):
        db.session.query(Slice).filter_by(slice_name=name).delete(); db.session.flush()
        sl = Slice(slice_name=name, viz_type=vt, datasource_type="table",
                   datasource_id=t.id, params=json.dumps(p))
        db.session.add(sl); db.session.flush()
        return sl.id

    C = {}
    # KPI band
    kpis = [("Total Employees", m_simple("Employee Count", "SUM"), ",d"),
            ("Attrition", m_simple("attrition_count", "SUM"), ",d"),
            ("Attrition Rate", m_sql('SUM(attrition_count)*1.0/SUM("Employee Count")', "rate"), ".1%"),
            ("Active Employees", m_sql('SUM("Employee Count")-SUM(attrition_count)', "active"), ",d"),
            ("Average Age", m_simple("Age", "AVG"), ".1f")]
    for lbl, met, fmt in kpis:
        C["kpi_" + lbl] = mk(f"{lbl} (HR)", "big_number_total", {
            "datasource": ds, "viz_type": "big_number_total", "metric": met,
            "subheader": lbl, "y_axis_format": fmt})

    # Attrition by Department (pie/donut)
    C["dept"] = mk("Attrition by Department (HR)", "pie", {
        "datasource": ds, "viz_type": "pie", "groupby": ["Department"],
        "metric": m_simple("attrition_count", "SUM"), "donut": True, "innerRadius": 45,
        "show_labels": True, "label_type": "key_value", "row_limit": 25})
    # Attrition by Gender (bar)
    C["gender"] = mk("Attrition by Gender (HR)", "echarts_timeseries_bar", {
        "datasource": ds, "viz_type": "echarts_timeseries_bar", "x_axis": "Gender",
        "metrics": [m_simple("attrition_count", "SUM")], "row_limit": 25})
    # No. of Employees by Age Group (bar)
    C["age"] = mk("Employees by Age Group (HR)", "echarts_timeseries_bar", {
        "datasource": ds, "viz_type": "echarts_timeseries_bar", "x_axis": "CF_age band",
        "metrics": [m_simple("Employee Count", "SUM")], "row_limit": 25,
        "x_axis_sort_asc": True})
    # Education Field wise (bar, horizontal-ish)
    C["edu"] = mk("Employees by Education Field (HR)", "echarts_timeseries_bar", {
        "datasource": ds, "viz_type": "echarts_timeseries_bar", "x_axis": "Education Field",
        "metrics": [m_simple("Employee Count", "SUM")], "row_limit": 25,
        "x_axis_sort_by": "Employee Count", "x_axis_sort_asc": False})
    # Job Satisfaction heatmap (Job Role x Satisfaction)
    C["jobsat"] = mk("Job Satisfaction Rating (HR)", "heatmap_v2", {
        "datasource": ds, "viz_type": "heatmap_v2", "x_axis": "Job Satisfaction",
        "groupby": "Job Role", "metric": m_simple("Employee Count", "SUM"),
        "linear_color_scheme": "superset_seq_1", "show_values": True, "row_limit": 500})
    # Attrition by Gender x Age band (grouped bar)
    C["genage"] = mk("Attrition by Gender & Age Band (HR)", "echarts_timeseries_bar", {
        "datasource": ds, "viz_type": "echarts_timeseries_bar", "x_axis": "CF_age band",
        "groupby": ["Gender"], "metrics": [m_simple("attrition_count", "SUM")],
        "row_limit": 50, "x_axis_sort_asc": True})
    db.session.commit()
    print("charts:", C)

    def node(cid, nm, w, h, r):
        return {"type": "CHART", "id": f"CHART-{cid}", "children": [],
                "parents": ["ROOT_ID", "GRID_ID", r],
                "meta": {"chartId": cid, "width": w, "height": h, "sliceName": nm}}
    pos = {"DASHBOARD_VERSION_KEY": "v2",
           "ROOT_ID": {"type": "ROOT", "id": "ROOT_ID", "children": ["GRID_ID"]},
           "GRID_ID": {"type": "GRID", "id": "GRID_ID", "parents": ["ROOT_ID"],
                       "children": ["R1", "R2", "R3"]},
           "HEADER_ID": {"type": "HEADER", "id": "HEADER_ID", "meta": {"text": "HR Analytics"}}}
    layout = {"R1": [(C["kpi_Total Employees"], "Total", 2, 28), (C["kpi_Attrition"], "Attrition", 2, 28),
                     (C["kpi_Attrition Rate"], "Rate", 3, 28), (C["kpi_Active Employees"], "Active", 2, 28),
                     (C["kpi_Average Age"], "Avg Age", 3, 28)],
              "R2": [(C["dept"], "Dept", 4, 50), (C["gender"], "Gender", 4, 50), (C["age"], "Age", 4, 50)],
              "R3": [(C["edu"], "Education", 4, 50), (C["jobsat"], "JobSat", 4, 50), (C["genage"], "GenAge", 4, 50)]}
    for rid, items in layout.items():
        pos[rid] = {"type": "ROW", "id": rid, "parents": ["ROOT_ID", "GRID_ID"],
                    "children": [], "meta": {"background": "BACKGROUND_TRANSPARENT"}}
        for cid, nm, w, h in items:
            pos[rid]["children"].append(f"CHART-{cid}")
            pos[f"CHART-{cid}"] = node(cid, nm, w, h, rid)

    db.session.query(Dashboard).filter_by(dashboard_title=DASH).delete(); db.session.commit()
    ids = list(C.values())
    d = Dashboard(dashboard_title=DASH, slug="hr-migrated", position_json=json.dumps(pos),
                  published=True, slices=[db.session.query(Slice).get(c) for c in ids])
    db.session.add(d); db.session.commit()
    print(f"DASHBOARD id={d.id} '{DASH}' with {len(ids)} charts")
    print(f"open: http://localhost:8088/superset/dashboard/{d.id}/")
