#!/usr/bin/env python3
"""
migrate.py — automated Tableau .twbx -> semantic extraction + ground-truth values.

For ANY .twbx it:
  1. unpacks the .hyper and reads every table into pandas
  2. parses the .twb: builds the column-instance map, then per worksheet extracts
     measures (aggregations) and filters (categorical / quantitative)
  3. classifies each worksheet: SIMPLE_AGG (translatable & verifiable) vs
     NEEDS_REVIEW (LOD / table-calc) vs UNSUPPORTED (viz extension)
  4. computes the ground-truth number for every SIMPLE_AGG measure from the data +
     the extracted filter -- this is the value a faithful Superset chart MUST match.

This is the "numbers always match" engine: it never guesses a target, it derives
it from the workbook, and anything it cannot derive is flagged, not shipped.
"""
import sys, glob, zipfile, tempfile, os, json, re
import xml.etree.ElementTree as ET
import pandas as pd
import pantab

AGG = {  # Tableau derivation -> (superset aggregate, pandas reducer)
    "Sum": ("SUM", lambda s: s.sum()),
    "Avg": ("AVG", lambda s: s.mean()),
    "Count": ("COUNT", lambda s: s.count()),
    "CountD": ("COUNT_DISTINCT", lambda s: s.nunique()),
    "Min": ("MIN", lambda s: s.min()),
    "Max": ("MAX", lambda s: s.max()),
}
DATE_DERIV = {"Year", "Month", "Day", "Quarter", "Week"}
TABLECALC = re.compile(r"WINDOW_|RUNNING_|INDEX\(|RANK\(|LOOKUP\(|TOTAL\(|FIRST\(|LAST\(", re.I)
LOD = re.compile(r"\{\s*(FIXED|INCLUDE|EXCLUDE)", re.I)


def load_hyper(twbx):
    tmp = tempfile.mkdtemp()
    with zipfile.ZipFile(twbx) as z:
        z.extractall(tmp)
    twb = glob.glob(f"{tmp}/**/*.twb", recursive=True)[0]
    hypers = glob.glob(f"{tmp}/**/*.hyper", recursive=True)
    frames = {}
    if hypers:
        frames = {str(k[-1]): v for k, v in pantab.frames_from_hyper(hypers[0]).items()}
    return twb, frames


def clean(name):  # [Order Date] -> Order Date
    return name.strip("[]")


def build_instance_map(root):
    """name (e.g. [yr:Order Date:ok]) -> (base_column, derivation)."""
    inst = {}
    for ci in root.iter("column-instance"):
        n = ci.get("name")
        if n:
            inst[n] = (clean(ci.get("column", "")), ci.get("derivation", "None"))
    return inst


def calc_formulas(root):
    """calc field caption/name -> formula (to detect LOD / table calcs)."""
    formulas = {}
    for col in root.iter("column"):
        calc = col.find("calculation")
        if calc is not None and calc.get("class") == "tableau":
            formulas[clean(col.get("name", ""))] = calc.get("formula", "") or ""
    return formulas


def parse_filters(ws, inst):
    """Return list of {col, deriv, kind, members|range} for categorical/quant filters."""
    out = []
    for f in ws.iter("filter"):
        cls = f.get("class")
        colref = f.get("column", "")            # e.g. [Sample - Superstore].[yr:Order Date:ok]
        m = re.search(r"\[[^\]]*\]\.(\[[^\]]*\])$", colref)
        instname = m.group(1) if m else colref
        base, deriv = inst.get(instname, (clean(instname), "None"))
        if cls == "categorical":
            members = [gf.get("member") for gf in f.iter("groupfilter")
                       if gf.get("function") == "member" and gf.get("member") is not None]
            if members and not base.startswith(":"):     # skip Measure Names etc.
                out.append({"col": base, "deriv": deriv, "kind": "in", "members": members})
        elif cls == "quantitative":
            mn, mx = f.find("min"), f.find("max")
            rng = {"min": mn.text if mn is not None else None,
                   "max": mx.text if mx is not None else None}
            if base and not base.startswith(":"):
                out.append({"col": base, "deriv": deriv, "kind": "range", "range": rng})
    return out


def apply_filters(df, filters):
    mask = pd.Series(True, index=df.index)
    for flt in filters:
        col = flt["col"]
        if col not in df.columns:
            return None  # can't verify -> caller flags
        s = df[col]
        if flt["deriv"] == "Year":
            s = pd.to_datetime(s).dt.year.astype(str)
            members = [str(int(float(x))) if str(x).replace('.', '').isdigit() else str(x) for x in flt["members"]]
        else:
            members = flt["members"] if flt["kind"] == "in" else None
        if flt["kind"] == "in":
            mask &= s.astype(str).isin([str(x) for x in members])
        elif flt["kind"] == "range":
            r = flt["range"]
            if r["min"] is not None: mask &= pd.to_numeric(df[col], errors="coerce") >= float(r["min"])
            if r["max"] is not None: mask &= pd.to_numeric(df[col], errors="coerce") <= float(r["max"])
    return df[mask]


def where_sql(filters):
    """Translate extracted filters into a Superset/Postgres WHERE predicate."""
    parts = []
    for f in filters:
        col = f['col'].replace('"', '""')
        if f['kind'] == 'in':
            if f['deriv'] == 'Year':
                vals = ",".join(str(int(float(m))) for m in f['members'])
                parts.append(f'EXTRACT(year FROM "{col}") IN ({vals})')
            else:
                vals = ",".join("'" + str(m).replace("'", "''") + "'" for m in f['members'])
                parts.append(f'"{col}" IN ({vals})')
        elif f['kind'] == 'range':
            r = f['range']
            if r.get('min') is not None:
                parts.append(f'"{col}" >= {float(r["min"])}')
            if r.get('max') is not None:
                parts.append(f'"{col}" <= {float(r["max"])}')
    return " AND ".join(parts)


def worksheet_measures(ws, inst):
    """Aggregated measures actually referenced on this sheet."""
    seen, meas = set(), []
    for ci in ws.iter("column-instance"):
        deriv = ci.get("derivation")
        if deriv in AGG:
            base = clean(ci.get("column", ""))
            key = (base, deriv)
            if key not in seen:
                seen.add(key); meas.append({"col": base, "agg": deriv})
    return meas


def classify(ws, measures, filters, formulas, frames):
    marks = [m.get("class") for m in ws.iter("mark")]
    if any(m == "VizExtension" for m in marks):
        return "UNSUPPORTED", "viz extension (no Superset equivalent)"
    # does any referenced calc use LOD / table calc?
    for ci in ws.iter("column-instance"):
        base = clean(ci.get("column", ""))
        fml = formulas.get(base, "")
        if TABLECALC.search(fml): return "NEEDS_REVIEW", "table calc"
        if LOD.search(fml):       return "NEEDS_REVIEW", "LOD expression"
    if measures:
        # ensure the measure column exists in some frame
        for fr in frames.values():
            if measures[0]["col"] in fr.columns:
                return "SIMPLE_AGG", "aggregation + filters"
    return "NEEDS_REVIEW", "no directly translatable aggregate measure"


def main(twbx):
    twb, frames = load_hyper(twbx)
    # pick the primary frame (has most business columns); may be None if the
    # workbook ships no packaged extract (live connection) -> structure only.
    main_df = max(frames.values(), key=lambda d: d.shape[1]) if frames else None
    root = ET.parse(twb).getroot()
    inst = build_instance_map(root)
    formulas = calc_formulas(root)

    print(f"WORKBOOK: {os.path.basename(twbx)}")
    if main_df is None:
        print("tables: (none) — no packaged extract; live/external connection. "
              "Parsing semantic model + classifying structure only.\n")
    else:
        print(f"tables: {list(frames)}  |  primary rows={len(main_df)}  cols={main_df.shape[1]}\n")

    report, counts = [], {"SIMPLE_AGG": 0, "NEEDS_REVIEW": 0, "UNSUPPORTED": 0}
    for ws in root.iter("worksheet"):
        name = ws.get("name")
        if not name:
            continue  # skip worksheet stubs/references without a name
        measures = worksheet_measures(ws, inst)
        filters = parse_filters(ws, inst)
        klass, reason = classify(ws, measures, filters, formulas, frames)
        counts[klass] += 1
        row = {"sheet": name, "class": klass, "reason": reason,
               "measures": measures, "filters": filters,
               "sql_where": where_sql(filters), "values": []}
        if klass == "SIMPLE_AGG" and main_df is None:
            row["class"] = "NEEDS_DATA"
            row["reason"] = "no packaged extract — connect the source to verify numbers"
            counts["SIMPLE_AGG"] -= 1
            counts.setdefault("NEEDS_DATA", 0)
            counts["NEEDS_DATA"] += 1
        elif klass == "SIMPLE_AGG":
            fdf = apply_filters(main_df, filters)
            if fdf is None:
                row["class"] = "NEEDS_REVIEW"; row["reason"] = "filter col not in data"
                counts["SIMPLE_AGG"] -= 1; counts["NEEDS_REVIEW"] += 1
            else:
                for meas in measures:
                    if meas["col"] in fdf.columns:
                        val = AGG[meas["agg"]][1](fdf[meas["col"]])
                        row["values"].append({"metric": f'{meas["agg"]}({meas["col"]})',
                                              "column": meas["col"],
                                              "aggregate": AGG[meas["agg"]][0],
                                              "expected": float(val)})
        report.append(row)

    # ---- print ----
    for r in report:
        tag = {"SIMPLE_AGG": "✅", "NEEDS_REVIEW": "🟨",
               "UNSUPPORTED": "🟥", "NEEDS_DATA": "⬜"}[r["class"]]
        filt = "; ".join(
            (f'{f["col"]}{"(year)" if f["deriv"]=="Year" else ""} IN {f["members"]}'
             if f["kind"] == "in" else f'{f["col"]} in {f["range"]}') for f in r["filters"]
        ) or "(none)"
        print(f'{tag} {r["sheet"]:<16} [{r["class"]}] {r["reason"]}')
        if r["filters"]:
            print(f'      filter: {filt}')
        for v in r["values"]:
            print(f'      → {v["metric"]} = {v["expected"]:,.0f}   (ground truth for numeric-diff)')
    print(f'\nSUMMARY: {counts["SIMPLE_AGG"]} auto-verifiable, '
          f'{counts["NEEDS_REVIEW"]} needs review, {counts["UNSUPPORTED"]} unsupported '
          f'(of {len(report)} worksheets)')
    json.dump(report, open("migration_plan.json", "w"), indent=2, default=str)
    print("wrote migration_plan.json")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else
         "/Users/amaannawab/Desktop/OverviewDashboard.twbx")
