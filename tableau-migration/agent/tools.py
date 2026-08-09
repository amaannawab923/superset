"""Deterministic tools the tile-agent orchestrates (Phase 1).

The agent does judgment (routing, Fix); these tools do the mechanical work and
own every number. We reuse the spike's proven pandas oracle (`migrate.py`) for
ground truth, and execute the *translated* SQL over the same `.hyper` frame with
DuckDB — an independent engine, so a wrong translation shows up as a numeric
mismatch instead of silently shipping. No live Superset required to prove the loop.
"""

import os
import sys
import xml.etree.ElementTree as ET

import duckdb

# Reuse the spike's parser + pandas oracle.
_SPIKE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "spike"))
if _SPIKE not in sys.path:
    sys.path.insert(0, _SPIKE)
import migrate  # noqa: E402


def load_workbook(twbx):
    """Parse a .twbx into (xml root, instance-map, calc-formulas, primary frame)."""
    twb, frames = migrate.load_hyper(twbx)
    root = ET.parse(twb).getroot()
    inst = migrate.build_instance_map(root)
    formulas = migrate.calc_formulas(root)
    primary = max(frames.values(), key=lambda d: d.shape[1]) if frames else None
    return root, inst, formulas, frames, primary


def plan_tiles(root, inst, formulas, frames):
    """One TilePlan per named worksheet, with the spike's classification."""
    tiles = []
    for ws in root.iter("worksheet"):
        name = ws.get("name")
        if not name:
            continue
        measures = migrate.worksheet_measures(ws, inst)
        filters = migrate.parse_filters(ws, inst)
        klass, reason = migrate.classify(ws, measures, filters, formulas, frames)
        tiles.append(
            {
                "sheet": name,
                "class": klass,
                "reason": reason,
                "measures": measures,
                "filters": filters,
            }
        )
    return tiles


def data_oracle(tile, primary):
    """Tier-0 ground truth: pandas over the filtered frame. Independent of the SQL."""
    fdf = migrate.apply_filters(primary, tile["filters"])
    if fdf is None:
        return None
    out = {}
    for m in tile["measures"]:
        if m["col"] in fdf.columns:
            out[f'{m["agg"]}({m["col"]})'] = float(migrate.AGG[m["agg"]][1](fdf[m["col"]]))
    return out


def translate_sql(tile):
    """Deterministic translate: measures -> aggregate SQL + WHERE (simple-agg path).

    Returns a spec: {"select": [(label, sql_expr)...], "where": predicate}.
    """
    where = migrate.where_sql(tile["filters"])
    select = []
    for m in tile["measures"]:
        agg = migrate.AGG[m["agg"]][0]  # SUM / AVG / COUNT / COUNT_DISTINCT / MIN / MAX
        col = m["col"].replace('"', '""')
        expr = f'COUNT(DISTINCT "{col}")' if agg == "COUNT_DISTINCT" else f'{agg}("{col}")'
        select.append((f'{m["agg"]}({m["col"]})', expr))
    return {"select": select, "where": where}


def execute_sql(spec, primary):
    """GOT: run the translated SQL over the frame with DuckDB (independent engine).

    Returns (values_by_label, the_query_text).
    """
    con = duckdb.connect()
    con.register("t", primary)
    cols = ", ".join(f'{expr} AS "{label}"' for label, expr in spec["select"])
    query = f"SELECT {cols} FROM t" + (f" WHERE {spec['where']}" if spec["where"] else "")
    try:
        row = con.execute(query).fetchone()
    except Exception as e:  # never crash the run; a failed execution is a flag
        return {"__error__": str(e).splitlines()[0]}, query
    labels = [label for label, _ in spec["select"]]
    got = {label: (float(v) if v is not None else None) for label, v in zip(labels, row)}
    return got, query


def numeric_diff(oracle, got, tol=1e-6):
    """Compare every oracle value to the executed result within tolerance."""
    diffs = {}
    for label, expected in oracle.items():
        g = got.get(label)
        ok = g is not None and abs(expected - g) <= tol * max(1.0, abs(expected))
        diffs[label] = {"expected": expected, "got": g, "ok": ok}
    numeric_ok = bool(diffs) and all(d["ok"] for d in diffs.values())
    return numeric_ok, diffs


def structural_diff(tile, spec):
    """Does the built tile's measure set match the .twb shelf spec?

    Catches the "used the wrong field" slip: the shelf said one measure, the
    translation emitted another. For the simple-agg path the labels are derived
    from the shelf, so this is an exact set check that stays honest once the LLM
    Fix node can diverge from the deterministic translation.
    """
    shelf = {f'{m["agg"]}({m["col"]})' for m in tile["measures"]}
    built = {label for label, _ in spec["select"]}
    return shelf == built, {"shelf": sorted(shelf), "built": sorted(built)}
