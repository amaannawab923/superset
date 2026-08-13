"""Tableau Analyst agent (Migration Buddy multi-agent Phase B — see
docs/MIGRATION_BUDDY_MULTI_AGENT.md §3). Read-only: given one calc field's
full formula chain, the current value of any Tableau parameters it uses,
and grounding from describe_workbook's workbook-wide summary, it emits a
calc_ir.Expr — never SQL, never pandas code, never a verdict. The
deterministic compiler in calc_ir.py (proven by hand in Phase A) turns
whatever it emits into SQL and pandas independently, and the existing
oracle-diff machinery in verify.py is the only thing that can promote a
tile to GREEN. This agent's opinion of its own translation is not a
verification — see the architecture doc's §1 for why that split matters.

No MCP tools, no access to Superset — this agent never writes anything. The
boundary is structural (it simply isn't given those tools), not just a
prompt instruction.
"""
from __future__ import annotations

import json
import logging
import re
from typing import TypedDict
from xml.etree.ElementTree import Element

import pandas as pd
from langchain_core.messages import HumanMessage, SystemMessage

from ..llm import build_llm
from . import calc_ir, tableau_parse as tp
from .parsing import ChartPlan

logger = logging.getLogger(__name__)

_PARAM_REF_RE = re.compile(r"\[Parameters\]\.\[([^\]]+)\]")
_BRACKETED_RE = re.compile(r"\[([^\]]+)\]")

_SYSTEM_PROMPT = """\
You are a Tableau calculation expert. You translate one Tableau calculated \
field's formula (plus every calc field it references, already resolved for \
you) into a small JSON expression tree — never SQL, never pandas or Python \
code, never a plain-language explanation shipped as the answer.

Use ONLY this vocabulary — nothing else is valid:
  {"op": "col", "name": "<a physical column from Available columns>"}
  {"op": "lit", "value": <number or string>}
  {"op": "param", "name": "<a Tableau parameter name>"}
  {"op": "add" | "sub" | "mul" | "div", "args": [<Expr>, <Expr>]}
  {"op": "gte" | "lte" | "gt" | "lt" | "eq", "args": [<Expr>, <Expr>]}
                                                        (a boolean comparison)
  {"op": "and" | "or", "args": [<Expr>, <Expr>]}       (boolean combination)
  {"op": "case", "on": <Expr>, "when": [[<match_value>, <Expr>], ...], \
"else": <Expr> | null}

Rules:
- Reference ONLY physical columns listed under "Available columns" — never \
invent a column name, never reference another Calculation_* field by name \
(inline its resolved formula instead — you were given the full chain).
- For a "case" whose "on" is a parameter, list every branch from the \
Tableau formula's WHEN clauses. A separate deterministic step resolves the \
parameter's current value and picks the branch — you do not need to (and \
should not) pre-resolve it yourself.
- A bare Tableau date literal in a formula, written as #2024-06-30# (with \
the # marks), becomes {"op": "lit", "value": "2024-06-30"} — strip the # \
marks, keep the date as a plain "YYYY-MM-DD" string.
- If the formula needs something outside this vocabulary — string \
functions, date functions (DATEPART, DATETRUNC, DATEDIFF, ...), LOD \
expressions (FIXED/INCLUDE/EXCLUDE), table calcs \
(WINDOW_/RANK/INDEX/LOOKUP/TOTAL/RUNNING_), or nested aggregations — do not \
approximate it. Respond with exactly:
  {"unsupported": true, "reason": "<one sentence naming what's missing>"}
- Output ONLY the JSON object on its own. No markdown fences, no prose \
before or after it.

Example 1 — a parameter-driven metric switcher:
  Formula chain given:
    Calculation_A = CASE [Parameters].[Parameter 1]
      WHEN 1 THEN [Calculation_B]
      WHEN 2 THEN [Quantity]
      WHEN 3 THEN [Total Sales]
      END
    Calculation_B = [Quantity]*[Sales Price]
  Correct answer:
  {"op": "case", "on": {"op": "param", "name": "Parameter 1"},
   "when": [[1, {"op": "mul", "args": [{"op": "col", "name": "Quantity"}, \
{"op": "col", "name": "Sales Price"}]}],
            [2, {"op": "col", "name": "Quantity"}],
            [3, {"op": "col", "name": "Total Sales"}]],
   "else": null}

Example 2 — a plain conditional on a real column:
  Formula chain given:
    Calculation_C = IF [International Shipping]='Yes' THEN 'International' \
ELSE 'Domestic' END
  Correct answer:
  {"op": "case", "on": {"op": "col", "name": "International Shipping"},
   "when": [["Yes", {"op": "lit", "value": "International"}]],
   "else": {"op": "lit", "value": "Domestic"}}

Example 3 — a two-sided date-range filter (a boolean-valued calc, often \
used as a context filter checked against "true"):
  Formula chain given:
    Calculation_D = [Order Date] >= [Parameters].[Parameter 4]
      AND [Order Date] <= [Calculation_E]
    Calculation_E = #2024-06-30#
  Current parameter values given: Parameter 4 = '2024-01-01'
  Correct answer:
  {"op": "and", "args": [
    {"op": "gte", "args": [{"op": "col", "name": "Order Date"}, \
{"op": "param", "name": "Parameter 4"}]},
    {"op": "lte", "args": [{"op": "col", "name": "Order Date"}, \
{"op": "lit", "value": "2024-06-30"}]}
  ]}
"""


class AnalystResult(TypedDict):
    calc_id: str
    expr: calc_ir.Expr | None
    params: dict[str, str]
    supported: bool
    reason: str | None  # set when supported is False, or on a parse/compile failure
    raw_response: str


def _extract_json(text: str) -> str:
    """Strip a ```json ... ``` fence if the model added one despite being
    told not to — same defensive-parsing posture as llm.py's title
    generation, which also doesn't trust the model to follow formatting
    instructions exactly."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[: -len("```")]
    return text.strip()


def _referenced_columns(chain: dict[str, str], primary_columns: list[str]) -> list[str]:
    """Every bracketed token across the formula chain that's actually a
    physical column in the extract — for the "Available columns" prompt
    section and the data sample, so the Analyst is grounded in real
    column names rather than guessing at spelling."""
    cols: set[str] = set()
    for formula in chain.values():
        for token in _BRACKETED_RE.findall(formula):
            if token in primary_columns:
                cols.add(token)
    return sorted(cols)


def _referenced_params(chain: dict[str, str]) -> list[str]:
    params: set[str] = set()
    for formula in chain.values():
        params.update(_PARAM_REF_RE.findall(formula))
    return sorted(params)


async def analyze_calc_field(
    root: Element,
    formulas: dict[str, str],
    primary: pd.DataFrame,
    calc_id: str,
    workbook_context: str,
) -> AnalystResult:
    """Translate one calc field into a calc_ir.Expr. Read-only: resolves
    the formula chain and parameter values itself (tableau_parse.py
    primitives), samples the extract for grounding, then asks the LLM for
    the expression tree — nothing here writes to Superset or executes
    anything against the extract beyond a read-only sample."""
    chain = tp.resolve_calc_chain(formulas, calc_id)
    if not chain:
        return AnalystResult(
            calc_id=calc_id, expr=None, params={}, supported=False,
            reason=f"{calc_id!r} has no formula in this workbook (not a calc field?)",
            raw_response="",
        )

    param_names = _referenced_params(chain)
    params = {name: tp.parameter_value(root, f"[Parameters].[{name}]") for name in param_names}
    unresolved = [name for name, value in params.items() if value is None]
    if unresolved:
        return AnalystResult(
            calc_id=calc_id, expr=None, params={}, supported=False,
            reason=f"parameter(s) {unresolved} referenced but not found in the workbook",
            raw_response="",
        )

    cols = _referenced_columns(chain, list(primary.columns))
    sample = primary[cols].head(5).to_dict("records") if cols else []

    chain_text = "\n".join(f"  {cid} = {formula}" for cid, formula in chain.items())
    params_text = "\n".join(f"  {name} = {value!r}" for name, value in params.items()) or "  (none)"
    prompt = f"""\
Workbook context (for grounding — how this field fits into the rest of the \
dashboard; you don't need to reference this in your answer, it's background):
{workbook_context}

Calc field to translate: {calc_id}
Formula chain (this calc, plus every calc it references, resolved):
{chain_text}

Current parameter values:
{params_text}

Available columns in the extract: {cols}

Sample rows: {sample}
"""

    llm = build_llm(enable_tools=False)
    response = await llm.ainvoke(
        [SystemMessage(content=_SYSTEM_PROMPT), HumanMessage(content=prompt)]
    )
    raw = str(response.content).strip()

    try:
        parsed = json.loads(_extract_json(raw))
    except json.JSONDecodeError as exc:
        logger.warning("Analyst: unparseable response for %s: %s", calc_id, raw[:500])
        return AnalystResult(
            calc_id=calc_id, expr=None, params=params, supported=False,
            reason=f"model response wasn't valid JSON: {exc}", raw_response=raw,
        )

    if parsed.get("unsupported"):
        return AnalystResult(
            calc_id=calc_id, expr=None, params=params, supported=False,
            reason=parsed.get("reason", "model reported this pattern as unsupported"),
            raw_response=raw,
        )

    # Validate by actually compiling both sides — an Expr that doesn't
    # compile is exactly as unusable as one the model explicitly declined,
    # so it gets the same honest "not supported" outcome, not a guess.
    try:
        calc_ir.compile_sql(parsed, params)
        calc_ir.compile_pandas(parsed, params)
    except (calc_ir.CalcIRError, KeyError, TypeError) as exc:
        logger.warning("Analyst: %s emitted an Expr that doesn't compile: %s", calc_id, exc)
        return AnalystResult(
            calc_id=calc_id, expr=None, params=params, supported=False,
            reason=f"emitted expression doesn't compile: {exc}", raw_response=raw,
        )

    return AnalystResult(
        calc_id=calc_id, expr=parsed, params=params, supported=True,
        reason=None, raw_response=raw,
    )


async def resolve_tile(
    root: Element,
    formulas: dict[str, str],
    primary: pd.DataFrame,
    tile: ChartPlan,
    workbook_context: str,
) -> ChartPlan:
    """Attempt to promote one NEEDS_REVIEW tile to SIMPLE_AGG by resolving
    every calc-field measure/dim it references through the Tableau
    Analyst. All-or-nothing: a tile only promotes if EVERY calc reference
    on it resolves — a tile half-resolved (one measure translated, one
    not) isn't safely buildable, so it stays NEEDS_REVIEW with the
    specific blocker(s) named instead of silently dropping the
    unresolved half.

    Deliberately doesn't pre-filter by the tile's ``reason`` text (table
    calc vs. LOD vs. calc field) — it just tries every measure/dim that
    references a formula, and trusts analyze_calc_field's own honest
    refusal (proven live: it correctly declines a table-calc pattern like
    RANK_UNIQUE rather than guessing) to gate out the genuinely
    unsupported cases. A tile with no calc-referencing measures/dims at
    all (a viz extension, a truly measure-less tile, ...) is untouched —
    there's nothing here this agent can help with.
    """
    if tile["klass"] != "NEEDS_REVIEW":
        return tile

    calc_measure_idxs = [i for i, m in enumerate(tile["measures"]) if m["col"] in formulas]
    calc_dim_idxs = [
        i for i, d in enumerate(tile["dims"]) if d["col"] in formulas and not d.get("synthetic")
    ]
    if not calc_measure_idxs and not calc_dim_idxs:
        return tile

    measures = list(tile["measures"])
    dims = list(tile["dims"])
    blockers: list[str] = []

    for i in calc_measure_idxs:
        m = measures[i]
        result = await analyze_calc_field(root, formulas, primary, m["col"], workbook_context)
        if not result["supported"]:
            blockers.append(f'{m["col"]}: {result["reason"]}')
            continue
        measures[i] = {**m, "resolved": {"expr": result["expr"], "params": result["params"]}}

    for i in calc_dim_idxs:
        d = dims[i]
        result = await analyze_calc_field(root, formulas, primary, d["col"], workbook_context)
        if not result["supported"]:
            blockers.append(f'{d["col"]}: {result["reason"]}')
            continue
        dims[i] = {**d, "resolved": {"expr": result["expr"], "params": result["params"]}}

    if blockers:
        return {
            **tile,
            "reason": "Tableau Analyst agent could not translate: " + "; ".join(blockers),
        }

    return {
        **tile,
        "klass": "SIMPLE_AGG",
        "measures": measures,
        "dims": dims,
        "reason": "calc field(s) translated by the Tableau Analyst agent",
    }
