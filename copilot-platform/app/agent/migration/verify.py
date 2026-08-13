"""Per-tile verify loop (Migration Buddy architecture doc §3/§4) — "flag,
don't fake". Generalizes tableau-migration/agent/tools.py + tile_graph.py
(proven scalar-only, fault-injection-tested) to also handle a dimensional
GROUP BY breakdown, since real dashboards are mostly bar/line/pie charts
with a dimension, not bare KPI numbers.

    translate -> oracle -> {execute|flag} -> verify -> {finalize_green|fix|flag}
                                                 ^                |
                                                 +---- execute <--+ (fix, retry)

Same discipline as the prototype: deterministic tools (translate_sql,
data_oracle, execute_sql, numeric_diff, structural_diff) own every number;
the LLM only proposes a revised translation in `fix`, gated by the same
verify checks on the way back around — a bad fix is caught exactly like a
bad first attempt, never shipped GREEN unverified.
"""
from __future__ import annotations

import json
import logging
from typing import Optional, TypedDict

import duckdb
import pandas as pd
from langgraph.graph import END, START, StateGraph

from . import tableau_parse as tp
from .parsing import ChartPlan

logger = logging.getLogger(__name__)

MAX_RETRIES = 2


class TileState(TypedDict, total=False):
    tile: ChartPlan
    oracle: Optional[dict]
    sql: dict
    got: dict
    query: str
    numeric_ok: bool
    structural_ok: bool
    diffs: dict
    struct: dict
    retries: int
    exec_error: str
    verdict: str  # GREEN | YELLOW | RED
    reason: str
    fix_note: str


# ---------------------------------------------------------------- deterministic tools

_DATE_EXTRACT = {
    "Year": "year",
    "Quarter": "quarter",
    "Month": "month",
    "Day": "day",
    "Week": "week",
}


def _sql_literal(value: str) -> str:
    """A bin/group member value as a SQL literal — bare if it parses as a
    number (Tableau never quotes numeric members in the .twb XML), quoted
    otherwise. Deciding by parseability rather than trusting a remembered
    "was this quoted in the XML" flag keeps this self-contained."""
    try:
        float(value)
        return value
    except ValueError:
        return "'" + value.replace("'", "''") + "'"


def _bin_sql_expr(spec: dict) -> str:
    col = spec["source_col"].replace('"', '""')
    peg, size = spec["peg"], spec["size"]
    expr = f'(FLOOR(("{col}" - {peg}) / {size}) * {size} + {peg})'
    if float(peg).is_integer() and float(size).is_integer():
        expr = f"CAST({expr} AS BIGINT)"  # matches the pandas Int64 oracle's plain-integer str()
    return expr


def _categorical_bin_sql_expr(spec: dict) -> str:
    col = spec["source_col"].replace('"', '""')
    whens = []
    for bucket in spec["buckets"]:
        members = ", ".join(_sql_literal(v) for v in bucket["values"])
        label = "'" + bucket["label"].replace("'", "''") + "'"
        whens.append(f'WHEN "{col}" IN ({members}) THEN {label}')
    return f'(CASE {" ".join(whens)} ELSE NULL END)'


def _dim_sql_expr(dim: dict) -> str:
    spec = dim.get("synthetic")
    if spec:
        return _bin_sql_expr(spec) if spec["kind"] == "bin" else _categorical_bin_sql_expr(spec)
    col = dim["col"].replace('"', '""')
    grain = _DATE_EXTRACT.get(dim.get("deriv"))
    return f'EXTRACT({grain} FROM "{col}")' if grain else f'"{col}"'


def _synthetic_dim_key(df: pd.DataFrame, spec: dict) -> pd.Series:
    s = df[spec["source_col"]]
    if spec["kind"] == "bin":
        peg, size = spec["peg"], spec["size"]
        key = ((s.astype(float) - peg) // size) * size + peg
        if float(peg).is_integer() and float(size).is_integer():
            return key.astype("Int64")  # nullable int: plain str() matches the SQL BIGINT cast
        return key.round(6)
    # categorical_bin: member -> label, matched by parsed type (numeric
    # column vs numeric-looking members compare as float; else as string) —
    # same float-parseability rule _sql_literal uses, so both sides agree
    # on which members are "numeric" without sharing state.
    numeric_map, string_map = {}, {}
    for bucket in spec["buckets"]:
        for v in bucket["values"]:
            try:
                numeric_map[float(v)] = bucket["label"]
            except ValueError:
                string_map[v] = bucket["label"]
    if pd.api.types.is_numeric_dtype(s) and not string_map:
        return s.astype(float).map(numeric_map)
    return s.astype(str).map({**string_map, **{str(k): v for k, v in numeric_map.items()}})


def _dim_key_series(df: pd.DataFrame, dim: dict) -> pd.Series:
    spec = dim.get("synthetic")
    if spec:
        return _synthetic_dim_key(df, spec)
    s = df[dim["col"]]
    grain = dim.get("deriv")
    if grain == "Year":
        return pd.to_datetime(s).dt.year
    if grain == "Quarter":
        return pd.to_datetime(s).dt.quarter
    if grain == "Month":
        return pd.to_datetime(s).dt.month
    if grain == "Day":
        return pd.to_datetime(s).dt.day
    if grain == "Week":
        return pd.to_datetime(s).dt.isocalendar().week.astype(int)
    return s


def translate_sql(tile: ChartPlan) -> dict:
    """{"select": [(label, sql_expr)], "groupby": [(label, sql_expr)], "where": str}.

    ``groupby`` entries are SELECTed alongside the aggregates and grouped by
    ordinal position — empty when the tile has no dimension (a scalar/KPI
    tile), same shape either way so execute_sql/numeric_diff don't need a
    separate scalar code path.
    """
    where = tp.where_sql(tile["filters"])
    groupby = [(d["col"], _dim_sql_expr(d)) for d in tile["dims"]]
    select = []
    for m in tile["measures"]:
        agg = tp.AGG[m["agg"]][0]
        col = m["col"].replace('"', '""')
        expr = f'COUNT(DISTINCT "{col}")' if agg == "COUNT_DISTINCT" else f'{agg}("{col}")'
        select.append((f'{m["agg"]}({m["col"]})', expr))
    return {"select": select, "groupby": groupby, "where": where}


def data_oracle(tile: ChartPlan, primary: pd.DataFrame) -> dict[tuple, dict] | None:
    """Row-keyed ground truth: {(dim values,): {measure_label: value}}.

    A scalar/no-dim tile has exactly one row, keyed by the empty tuple —
    this keeps execute_sql's DuckDB result and this pandas result in the
    same shape so numeric_diff needs only one comparison path. Returns None
    (unverifiable — not a wrong answer, an honest "can't check this") when a
    referenced column isn't in the primary frame at all.
    """
    for m in tile["measures"]:
        if m["col"] not in primary.columns:
            return None
    for d in tile["dims"]:
        # A synthetic (bin/categorical-bin) dim's own "column" is derived,
        # never a literal field in primary — check its real source column.
        needed_col = d["synthetic"]["source_col"] if d.get("synthetic") else d["col"]
        if needed_col not in primary.columns:
            return None
    fdf = tp.apply_filters(primary, tile["filters"])
    if fdf is None:
        return None

    if not tile["dims"]:
        row = {
            f'{m["agg"]}({m["col"]})': float(tp.AGG[m["agg"]][1](fdf[m["col"]]))
            for m in tile["measures"]
        }
        return {(): row}

    # A bin/categorical-bin dim can leave some source values unmapped (a
    # value outside every bucket) — DuckDB's GROUP BY keeps that as a real
    # NULL group (str(None) == "None" on the execute_sql side), but pandas'
    # multi-column groupby(..., dropna=False) has a real bug in this pandas
    # version (crashes building .groups for an object-dtype None key), and
    # even sidestepping that by iterating directly, it silently re-coerces
    # a preserved None back to NaN for the group key. Rather than fight
    # pandas' internal missing-key handling, stringify every key up front
    # (mapping missing -> the literal "None", matching execute_sql's
    # str(None)) so there's no NaN left for groupby to mishandle at all —
    # this also makes every OTHER dim-grouping path (dates, raw columns)
    # equally NULL-safe, not just the synthetic-field one.
    keys = pd.concat(
        [
            _dim_key_series(fdf, d)
            .map(lambda v: "None" if pd.isna(v) else str(v))
            .rename(d["col"])
            for d in tile["dims"]
        ],
        axis=1,
    )
    out: dict[tuple, dict] = {}
    for group_key, gdf in fdf.groupby([keys[c] for c in keys.columns]):
        key = group_key if isinstance(group_key, tuple) else (group_key,)
        out[tuple(key)] = {
            f'{m["agg"]}({m["col"]})': float(tp.AGG[m["agg"]][1](gdf[m["col"]]))
            for m in tile["measures"]
        }
    return out


def execute_sql(spec: dict, primary: pd.DataFrame) -> tuple[dict, str]:
    """Run the translated SQL via an in-process DuckDB connection registered
    against ``primary`` (zero-copy pandas). Returns (got, query_text); on
    any execution error, ``got`` is ``{"__error__": message}`` — a sentinel
    that can never collide with a real row-key tuple, so callers can check
    ``"__error__" in got`` unconditionally."""
    con = duckdb.connect()
    con.register("t", primary)
    n_dims = len(spec["groupby"])
    select_parts = [f'{expr} AS "{label}"' for label, expr in spec["groupby"]]
    select_parts += [f'{expr} AS "{label}"' for label, expr in spec["select"]]
    query = f'SELECT {", ".join(select_parts)} FROM t'
    if spec["where"]:
        query += f' WHERE {spec["where"]}'
    if spec["groupby"]:
        query += f' GROUP BY {", ".join(str(i + 1) for i in range(n_dims))}'
    try:
        cur = con.execute(query)
        col_labels = [d[0] for d in cur.description]
        rows = cur.fetchall()
    except Exception as exc:  # noqa: BLE001 — a bad translation must flag, not crash the loop
        return {"__error__": str(exc).splitlines()[0]}, query
    finally:
        con.close()

    got: dict[tuple, dict] = {}
    for row in rows:
        key = tuple(str(v) for v in row[:n_dims])
        got[key] = {
            col_labels[n_dims + i]: (float(v) if v is not None else None)
            for i, v in enumerate(row[n_dims:])
        }
    return got, query


def numeric_diff(
    oracle: dict[tuple, dict] | None, got: dict, tol: float = 1e-6
) -> tuple[bool, dict]:
    """Row-by-row comparison on matching group keys. A group present in one
    side but not the other is a failure, not a silent skip."""
    if not oracle:
        return False, {}
    diffs: dict[str, dict] = {}
    ok = True
    for key in set(oracle) | set(got):
        key_label = "(all)" if key == () else "/".join(key)
        o_row, g_row = oracle.get(key), got.get(key)
        if o_row is None or g_row is None:
            ok = False
            diffs[key_label] = {
                "expected": o_row, "got": g_row, "ok": False,
                "reason": "group present in oracle but not built SQL"
                if g_row is None else "group present in built SQL but not oracle",
            }
            continue
        for label, expected in o_row.items():
            g = g_row.get(label)
            row_ok = g is not None and abs(expected - g) <= tol * max(1.0, abs(expected))
            ok = ok and row_ok
            diffs[f"{key_label}:{label}" if key else label] = {
                "expected": expected, "got": g, "ok": row_ok,
            }
    return ok, diffs


def structural_diff(tile: ChartPlan, spec: dict) -> tuple[bool, dict]:
    """Does the built SQL reference the same measures AND dimensions the
    Tableau shelf actually specified — catches e.g. "used the wrong column"
    slips that a numeric coincidence could otherwise hide."""
    shelf_measures = {f'{m["agg"]}({m["col"]})' for m in tile["measures"]}
    built_measures = {label for label, _ in spec["select"]}
    shelf_dims = {d["col"] for d in tile["dims"]}
    built_dims = {label for label, _ in spec["groupby"]}
    ok = shelf_measures == built_measures and shelf_dims == built_dims
    return ok, {
        "shelf_measures": sorted(shelf_measures), "built_measures": sorted(built_measures),
        "shelf_dims": sorted(shelf_dims), "built_dims": sorted(built_dims),
    }


# ---------------------------------------------------------------- LLM fix node

FIX_SYSTEM_PROMPT = (
    "You are fixing a SQL translation of a Tableau worksheet that failed "
    "numeric verification against the source data. You will be given the "
    "worksheet's measures/dimensions/filters, the current SQL translation, "
    "and the diff between the expected (oracle) values and what the SQL "
    "actually produced. Reply with ONLY a JSON object matching this exact "
    'shape: {"select": [[label, sql_expr], ...], "groupby": [[label, '
    'sql_expr], ...], "where": "sql predicate or empty string"} — same '
    "shape as the input spec. Fix the SQL expression(s) that produced wrong "
    "values; do not change labels or add/remove measures/dimensions unless "
    "the diff shows one is genuinely missing or extra. No prose, no markdown "
    "fences, just the JSON object."
)


async def _llm_fix(sql: dict, diffs: dict, tile: ChartPlan) -> dict:
    """A cheap, tool-free LLM call proposing a revised SQL spec. Never
    raises — any failure (bad JSON, wrong shape, LLM error) returns the
    original spec unchanged, so a broken fix just costs a retry rather than
    corrupting the translation or crashing the loop."""
    from ..llm import build_llm  # deferred: avoid a module cycle at import time

    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        llm = build_llm(enable_tools=False)
        payload = {
            "sheet": tile["sheet"],
            "measures": tile["measures"],
            "dims": tile["dims"],
            "current_sql": sql,
            "diffs": diffs,
        }
        response = await llm.ainvoke(
            [
                SystemMessage(content=FIX_SYSTEM_PROMPT),
                HumanMessage(content=json.dumps(payload, default=str)),
            ]
        )
        text = str(response.content).strip()
        if text.startswith("```"):
            text = text.strip("`").removeprefix("json").strip()
        revised = json.loads(text)
        if {"select", "groupby", "where"} <= revised.keys():
            revised["select"] = [tuple(p) for p in revised["select"]]
            revised["groupby"] = [tuple(p) for p in revised["groupby"]]
            return revised
    except Exception:  # noqa: BLE001 — a fix must never break verification
        logger.exception("Migration Buddy: LLM fix attempt failed, keeping prior SQL")
    return sql


# ---------------------------------------------------------------- the graph


def build_tile_graph(primary: pd.DataFrame, use_llm_fix: bool = True):
    """Compile a per-tile graph. ``primary`` is the workbook's .hyper frame
    (kept out of graph state — it's large and never needs to be serialized).
    A tile whose parsing.classify() verdict wasn't SIMPLE_AGG never reaches
    translate at all — see gate() below."""

    async def gate(state: TileState) -> str:
        tile = state["tile"]
        return "translate" if tile["klass"] == "SIMPLE_AGG" else "flag_unclassified"

    async def flag_unclassified(state: TileState) -> TileState:
        return {"verdict": "RED", "reason": state["tile"]["reason"]}

    async def translate(state: TileState) -> TileState:
        return {"sql": translate_sql(state["tile"]), "retries": state.get("retries", 0)}

    async def oracle(state: TileState) -> TileState:
        return {"oracle": data_oracle(state["tile"], primary)}

    async def execute(state: TileState) -> TileState:
        got, query = execute_sql(state["sql"], primary)
        return {"got": got, "query": query}

    async def verify(state: TileState) -> TileState:
        oc = state.get("oracle")
        got = state.get("got", {})
        structural_ok, struct = structural_diff(state["tile"], state["sql"])
        if "__error__" in got:
            return {
                "numeric_ok": False, "structural_ok": structural_ok,
                "struct": struct, "exec_error": got["__error__"],
            }
        numeric_ok, diffs = numeric_diff(oc, got)
        return {
            "numeric_ok": numeric_ok, "structural_ok": structural_ok,
            "diffs": diffs, "struct": struct,
        }

    async def fix(state: TileState) -> TileState:
        revised = await _llm_fix(state["sql"], state.get("diffs", {}), state["tile"])
        return {
            "sql": revised, "retries": state.get("retries", 0) + 1,
            "fix_note": "LLM revised translation from numeric diff",
        }

    async def finalize_green(state: TileState) -> TileState:
        return {"verdict": "GREEN", "reason": "numeric + structural match; SQL frozen"}

    async def flag(state: TileState) -> TileState:
        if not state.get("oracle"):
            return {
                "verdict": "YELLOW",
                "reason": f'unverified by data-oracle ({state["tile"]["reason"]}); '
                "needs a Tier-1 rendered oracle or human review",
            }
        if state.get("exec_error"):
            return {"verdict": "RED", "reason": f'could not execute translated SQL: {state["exec_error"]}'}
        if not state.get("structural_ok"):
            return {
                "verdict": "RED",
                "reason": f'structural mismatch: shelf {state["struct"]["shelf_measures"]}/'
                f'{state["struct"]["shelf_dims"]} != built {state["struct"]["built_measures"]}/'
                f'{state["struct"]["built_dims"]}',
            }
        return {"verdict": "RED", "reason": "numeric mismatch after retries exhausted"}

    def after_oracle(state: TileState) -> str:
        return "execute" if state.get("oracle") else "flag"

    def route(state: TileState) -> str:
        if state.get("numeric_ok") and state.get("structural_ok"):
            return "finalize_green"
        can_retry = (
            use_llm_fix
            and state.get("retries", 0) < MAX_RETRIES
            and bool(state.get("oracle"))
            and not state.get("numeric_ok")
        )
        return "fix" if can_retry else "flag"

    g = StateGraph(TileState)
    for name, fn in [
        ("translate", translate), ("oracle", oracle), ("execute", execute),
        ("verify", verify), ("fix", fix), ("finalize_green", finalize_green),
        ("flag", flag), ("flag_unclassified", flag_unclassified),
    ]:
        g.add_node(name, fn)

    g.add_conditional_edges(
        START, gate, {"translate": "translate", "flag_unclassified": "flag_unclassified"}
    )
    g.add_edge("translate", "oracle")
    g.add_conditional_edges("oracle", after_oracle, {"execute": "execute", "flag": "flag"})
    g.add_edge("execute", "verify")
    g.add_conditional_edges(
        "verify", route, {"finalize_green": "finalize_green", "fix": "fix", "flag": "flag"}
    )
    g.add_edge("fix", "execute")
    g.add_edge("finalize_green", END)
    g.add_edge("flag", END)
    g.add_edge("flag_unclassified", END)
    return g.compile()
