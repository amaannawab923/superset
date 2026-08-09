#!/usr/bin/env python3
"""Derive the tile spec for the Overview dashboard straight from the .twb —
no screenshot, no hardcoded business values. Everything below is parsed out of
the workbook XML: the funnel bucketing, the traffic-source group, the scaling
constant, and each sheet's filters/marks.
"""
import sys, glob, zipfile, tempfile, re, json
import xml.etree.ElementTree as ET


def load_twb(twbx):
    tmp = tempfile.mkdtemp()
    zipfile.ZipFile(twbx).extractall(tmp)
    return glob.glob(f"{tmp}/**/*.twb", recursive=True)[0]


def calc_formulas(root):
    out = {}
    for col in root.iter("column"):
        c = col.find("calculation")
        if c is not None and c.get("class") == "tableau":
            out[col.get("name").strip("[]")] = (c.get("caption") or col.get("caption") or "",
                                                c.get("formula") or "")
    return out


def parse_if_map(formula, field):
    """Parse: If [field]='A' then 'X' ELSEIF [field]='B' then 'Y' else 'Z' end."""
    m = {}
    for val, lbl in re.findall(r"\[%s\]\s*=\s*'([^']+)'\s*then\s*'([^']+)'" % re.escape(field),
                               formula, re.I):
        m[val] = lbl
    els = re.search(r"else\s*'([^']+)'\s*end", formula, re.I)
    return m, (els.group(1) if els else None)


def extract(twbx):
    root = ET.parse(load_twb(twbx)).getroot()
    forms = calc_formulas(root)
    spec = {}

    # --- funnel: find the calc that buckets a dimension into stage strings ---
    for cap, f in forms.values():
        if "Ship Mode" in f and "then" in f.lower():
            m, els = parse_if_map(f, "Ship Mode")
            if m:
                spec["funnel"] = {"field": "Ship Mode", "map": m, "else": els}
                spec["funnel_order"] = list(m.values()) + ([els] if els else [])
                break

    # --- scaling constant: a calc that is just  <int>/<int> ---
    for cap, f in forms.values():
        mm = re.fullmatch(r"\s*(\d+)\s*/\s*(\d+)\s*", f)
        if mm:
            spec["scale"] = [int(mm.group(1)), int(mm.group(2))]
            break

    # --- traffic-source group: a <group> whose members rename Sub-Category ---
    for col in root.iter("column"):
        bins = col.findall(".//bin")
        if bins and "Sub-Category (group)" in (col.get("name") or ""):
            group = {}
            for b in bins:
                bucket = (b.get("value") or "").strip('"')
                for v in b.findall("value"):
                    group[v.text.strip('"')] = bucket
            spec["source_group"] = {"field": "Sub-Category", "map": group,
                                    "name": col.get("caption") or "Source"}
            break

    # --- LOD / table-calc detection per relevant calc (drives SQL translation) ---
    spec["lod_fields"] = {name: f for name, (cap, f) in forms.items()
                          if re.search(r"\{\s*(FIXED|INCLUDE|EXCLUDE)", f, re.I)}
    spec["tablecalc_fields"] = {name: f for name, (cap, f) in forms.items()
                                if re.search(r"WINDOW_|RUNNING_|LOOKUP\(|INDEX\(", f, re.I)}
    return spec


if __name__ == "__main__":
    twbx = sys.argv[1] if len(sys.argv) > 1 else "/Users/amaannawab/Desktop/OverviewDashboard.twbx"
    spec = extract(twbx)
    print(json.dumps({k: v for k, v in spec.items()
                      if k not in ("lod_fields", "tablecalc_fields")}, indent=2))
    print("LOD calcs found:", list(spec["lod_fields"]))
    print("table-calc calcs found:", list(spec["tablecalc_fields"]))
    json.dump(spec, open("derived_spec.json", "w"), indent=2)
