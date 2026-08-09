"""build_ir.py — GENERIC Superset builder. Consumes ir.json (from engine.py) and
builds datasets + charts + a dashboard. No workbook-specific code.
Runs INSIDE the superset-light container (app context)."""
import json, re
import pandas as pd
from superset.app import create_app

app = create_app()
with app.app_context():
    from superset import db
    from superset.connectors.sqla.models import SqlaTable, TableColumn
    from superset.models.slice import Slice
    from superset.models.dashboard import Dashboard

    ir = json.load(open("/tmp/ir.json"))
    df = pd.read_parquet("/tmp/eng_primary.parquet")
    slug = re.sub(r"[^a-z0-9]+", "_", ir["workbook"].lower()).strip("_")[:24]
    TABLE = "eng_" + slug
    base = db.session.query(SqlaTable).filter_by(table_name="mig_orders").first()
    database = base.database

    with database.get_sqla_engine() as e:
        df.to_sql(TABLE, e, if_exists="replace", index=False, schema="public", chunksize=5000)
    t = db.session.query(SqlaTable).filter_by(table_name=TABLE, database_id=database.id).first()
    if not t:
        t = SqlaTable(table_name=TABLE, database=database, schema="public")
        db.session.add(t); db.session.flush()
    t.fetch_metadata()
    # refresh the engine's calc columns (drop stale cc_* from prior builds, re-add)
    t.columns = [c for c in t.columns if not c.column_name.startswith("cc_")]
    db.session.flush()
    for name, expr in ir["dataset"].get("calc_columns", {}).items():
        t.columns.append(TableColumn(column_name=name, expression=expr, type="VARCHAR"))
    db.session.commit()
    ds = f"{t.id}__table"
    print(f"dataset {TABLE} id={t.id} rows={len(df):,} (+{len(ir['dataset'].get('calc_columns',{}))} calc cols)")

    # virtual datasets for table-calc charts (chart carries its own SQL)
    import hashlib
    vds = {}

    def virtual_ds(sql):
        if sql in vds:
            return vds[sql]
        nm = "vds_" + hashlib.md5(sql.encode()).hexdigest()[:10]
        v = db.session.query(SqlaTable).filter_by(table_name=nm, database_id=database.id).first()
        if not v:
            v = SqlaTable(table_name=nm, database=database)
            db.session.add(v)
        v.sql = sql
        v.schema = None
        db.session.flush()
        v.fetch_metadata()
        db.session.commit()
        vds[sql] = v
        return v

    def sqlm(m):
        return {"expressionType": "SQL", "sqlExpression": m["sql"], "label": m["label"]}

    def adhoc(f):
        return [{"clause": "WHERE", "expressionType": "SQL", "sqlExpression": f}] if f else []

    def params_for(c, dsrc):
        mets = [sqlm(m) for m in c["measures"]]
        dims = c["dims"]
        af = adhoc(c["filter_sql"])
        vt = c["viz_type"]
        base = {"datasource": dsrc, "viz_type": vt, "adhoc_filters": af, "row_limit": 1000}
        if vt == "big_number_total":
            base["metric"] = mets[0] if mets else {"expressionType": "SQL",
                                                   "sqlExpression": "COUNT(*)", "label": "count"}
            base["subheader"] = c["name"]
        elif vt == "pie":
            base.update({"groupby": dims[:1], "metric": mets[0] if mets else
                         {"expressionType": "SQL", "sqlExpression": "COUNT(*)", "label": "count"}})
        elif vt in ("echarts_timeseries_bar", "echarts_timeseries_line"):
            base.update({"x_axis": dims[0] if dims else None, "groupby": dims[1:],
                         "metrics": mets or [{"expressionType": "SQL",
                                              "sqlExpression": "COUNT(*)", "label": "count"}]})
        elif vt == "heatmap_v2":
            base.update({"x_axis": dims[0] if dims else None,
                         "groupby": dims[1] if len(dims) > 1 else None,
                         "metric": mets[0] if mets else None})
        else:  # table (incl. flagged)
            base.update({"query_mode": "aggregate", "groupby": dims,
                         "metrics": mets or [{"expressionType": "SQL",
                                              "sqlExpression": "COUNT(*)", "label": "count"}]})
        return base

    made = []
    for i, c in enumerate(ir["charts"]):
        nm = f'{c["name"]} · {ir["workbook"][:10]}'
        db.session.query(Slice).filter_by(slice_name=nm).delete(); db.session.flush()
        try:
            if c.get("dataset_sql"):
                v = virtual_ds(c["dataset_sql"])
                dsid, dsrc = v.id, f"{v.id}__table"
            else:
                dsid, dsrc = t.id, ds
            sl = Slice(slice_name=nm, viz_type=c["viz_type"], datasource_type="table",
                       datasource_id=dsid, params=json.dumps(params_for(c, dsrc)))
            db.session.add(sl); db.session.flush()
            made.append((sl.id, nm, c))
        except Exception as ex:
            print("  skip", c["name"], str(ex)[:80])
    db.session.commit()

    # ---- layout from IR gw/gh + row grouping (row_y) ----
    pos = {"DASHBOARD_VERSION_KEY": "v2",
           "ROOT_ID": {"type": "ROOT", "id": "ROOT_ID", "children": ["GRID_ID"]},
           "GRID_ID": {"type": "GRID", "id": "GRID_ID", "parents": ["ROOT_ID"], "children": []},
           "HEADER_ID": {"type": "HEADER", "id": "HEADER_ID",
                         "meta": {"text": ir["dashboard_title"]}}}
    rows, cur, cy, used = [], [], None, 0
    for cid, nm, c in made:
        if cy is None or c["row_y"] - cy > 4000 or used + c["gw"] > 12:
            if cur: rows.append(cur)
            cur, cy, used = [(cid, c)], c["row_y"], c["gw"]
        else:
            cur.append((cid, c)); used += c["gw"]
    if cur: rows.append(cur)
    for ri, r in enumerate(rows):
        rid = f"ROW-{ri}"
        pos["GRID_ID"]["children"].append(rid)
        pos[rid] = {"type": "ROW", "id": rid, "parents": ["ROOT_ID", "GRID_ID"],
                    "children": [], "meta": {"background": "BACKGROUND_TRANSPARENT"}}
        for cid, c in r:
            k = f"CHART-{cid}"
            pos[rid]["children"].append(k)
            pos[k] = {"type": "CHART", "id": k, "children": [],
                      "parents": ["ROOT_ID", "GRID_ID", rid],
                      "meta": {"chartId": cid, "width": c["gw"], "height": c["gh"],
                               "sliceName": c["name"]}}

    title = ir["dashboard_title"]
    db.session.query(Dashboard).filter_by(dashboard_title=title).delete(); db.session.commit()
    d = Dashboard(dashboard_title=title, position_json=json.dumps(pos), published=True,
                  slices=[db.session.query(Slice).get(cid) for cid, _, _ in made])
    db.session.add(d); db.session.commit()
    print(f"DASHBOARD id={d.id} '{title}' with {len(made)} charts")
    print(f"open: http://localhost:8088/superset/dashboard/{d.id}/")
