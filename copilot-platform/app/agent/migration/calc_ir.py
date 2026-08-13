"""Declarative calc-field IR + deterministic compiler (Migration Buddy
multi-agent Phase A — see docs/MIGRATION_BUDDY_MULTI_AGENT.md §4).

An expression tree built from a small, fixed vocabulary of ops. The whole
point: compile the SAME tree to SQL (for the real chart) and to a pandas
callable (for the oracle) so the two can never silently diverge — unlike
independently-written SQL and pandas snippets, which could drift apart in
exactly the way a numeric diff can't catch. No LLM in this module — Phase A
proves the mechanism by hand before any agent writes an IR expression; a
future Analyst agent produces `Expr` dicts, it never writes SQL or pandas
code directly.

Expr shapes (a plain dict, JSON-serializable — the same shape an LLM agent
will eventually emit):
    {"op": "col", "name": str}                   a physical column
    {"op": "lit", "value": float | str}          a literal constant
    {"op": "param", "name": str}                 a Tableau parameter —
        resolved to its CURRENT value at compile time, not a runtime SQL
        construct (Tableau parameters aren't stored data; migrating a
        parameter-driven calc means freezing it at its published value,
        architecture doc principle #5 "freeze to replayable artifacts").
    {"op": "add"|"sub"|"mul"|"div", "args": [Expr, Expr]}
    {"op": "gte"|"lte"|"gt"|"lt"|"eq", "args": [Expr, Expr]}
                                                  a boolean comparison
    {"op": "and"|"or", "args": [Expr, Expr]}     boolean combination
    {"op": "case", "on": Expr, "when": [(match_value, Expr), ...],
     "else": Expr | None}
        If `on` resolves to a compile-time constant (a literal, or a
        parameter reference), the whole case collapses to whichever
        branch matches — no runtime CASE WHEN emitted at all, on either
        the SQL or the pandas side. If `on` is a real column, emits a
        genuine SQL CASE WHEN / pandas per-row branch.

Deliberately narrow: only the ops needed for real patterns actually seen —
the parameter-switcher (MerchandiseSales' Calculation_254383022497943554),
a plain conditional on a real column, and a two-sided date-range filter
(comparison + "and"). Grow the vocabulary per the construct catalog as new
patterns are encountered — not speculatively ahead of a real case.
"""
from __future__ import annotations

from typing import Any, Callable

import numpy as np
import pandas as pd

Expr = dict[str, Any]
Params = dict[str, str]

_ARITH_SQL = {"add": "+", "sub": "-", "mul": "*", "div": "/"}
_ARITH_PD: dict[str, Callable[[Any, Any], Any]] = {
    "add": lambda a, b: a + b,
    "sub": lambda a, b: a - b,
    "mul": lambda a, b: a * b,
    "div": lambda a, b: a / b,
}
_COMPARE_SQL = {"gte": ">=", "lte": "<=", "gt": ">", "lt": "<", "eq": "="}
_COMPARE_PD: dict[str, Callable[[Any, Any], Any]] = {
    "gte": lambda a, b: a >= b,
    "lte": lambda a, b: a <= b,
    "gt": lambda a, b: a > b,
    "lt": lambda a, b: a < b,
    "eq": lambda a, b: a == b,
}
_BOOL_SQL = {"and": "AND", "or": "OR"}
_BOOL_PD: dict[str, Callable[[Any, Any], Any]] = {
    "and": lambda a, b: a & b,
    "or": lambda a, b: a | b,
}


class CalcIRError(Exception):
    """An expression the compiler doesn't (yet) support, or a parameter
    reference it can't resolve. Surfaced, not silently guessed at — a tile
    whose IR hits this stays NEEDS_REVIEW, the same honest-failure shape an
    unsupported calc pattern already has today."""


def _resolve_const(expr: Expr, params: Params) -> str | float | None:
    """If `expr` is a compile-time constant (a literal, or a resolvable
    parameter reference), return its scalar value; otherwise None. Decides
    whether a `case`'s `on` collapses at compile time instead of emitting a
    runtime CASE WHEN."""
    if expr["op"] == "lit":
        return expr["value"]
    if expr["op"] == "param":
        if expr["name"] not in params:
            raise CalcIRError(f"unresolved parameter: {expr['name']!r}")
        return params[expr["name"]]
    return None


def _matches(const: str | float, candidate: Any) -> bool:
    """Loose equality for a case branch match — a Tableau formula compares
    a parameter's typed value (e.g. integer 1) against a `when` key that
    may be written as either 1 or "1" in the IR; compare as strings so the
    caller doesn't have to track the parameter's declared datatype."""
    return str(const) == str(candidate)


def _lit(value: str | float) -> Expr:
    return {"op": "lit", "value": value}


def _coerce_compare_operands(a: Any, b: Any) -> tuple[Any, Any]:
    """Align a Series-vs-scalar comparison's dtypes when the Series side is
    date-like. SQL handles ``"Order Date" >= '2024-01-01'`` via an implicit
    cast DuckDB does automatically; pandas doesn't do that for the
    pyarrow-backed date/timestamp dtypes pantab loads a .hyper extract's
    date columns as (e.g. ``date32[day][pyarrow]``) — comparing that
    directly against a plain string raises ``ArrowNotImplementedError``.
    Converting both sides through ``pd.to_datetime``/``pd.Timestamp``
    sidesteps the extension-dtype kernel entirely rather than special-
    casing pyarrow dtypes by name."""
    a_dtype, b_dtype = str(getattr(a, "dtype", "")), str(getattr(b, "dtype", ""))
    if isinstance(a, pd.Series) and not isinstance(b, pd.Series):
        if "date" in a_dtype or "timestamp" in a_dtype:
            return pd.to_datetime(a), pd.Timestamp(b)
    elif isinstance(b, pd.Series) and not isinstance(a, pd.Series):
        if "date" in b_dtype or "timestamp" in b_dtype:
            return pd.Timestamp(a), pd.to_datetime(b)
    return a, b


def eval_literal(expr: Expr, params: Params) -> str | float | None:
    """Public wrapper around the compile-time-constant check `case` uses
    internally — lets other modules (apply.py, decomposing a resolved
    filter's Expr into structured FilterConfig entries generate_chart
    accepts) ask "is this sub-expression just a constant, and if so what?"
    without reaching into a private helper."""
    return _resolve_const(expr, params)


def compile_sql(expr: Expr, params: Params) -> str:
    """Compile an Expr to a SQL fragment (unquoted identifiers get double-
    quoted, matching verify.py's existing SQL-building convention)."""
    op = expr["op"]
    if op == "col":
        col = expr["name"].replace('"', '""')
        return f'"{col}"'
    if op == "lit":
        v = expr["value"]
        if isinstance(v, (int, float)):
            return str(v)
        return "'" + str(v).replace("'", "''") + "'"
    if op == "param":
        if expr["name"] not in params:
            raise CalcIRError(f"unresolved parameter: {expr['name']!r}")
        return compile_sql(_lit(params[expr["name"]]), params)
    if op in _ARITH_SQL:
        a, b = expr["args"]
        return f"({compile_sql(a, params)} {_ARITH_SQL[op]} {compile_sql(b, params)})"
    if op in _COMPARE_SQL:
        a, b = expr["args"]
        return f"({compile_sql(a, params)} {_COMPARE_SQL[op]} {compile_sql(b, params)})"
    if op in _BOOL_SQL:
        a, b = expr["args"]
        return f"({compile_sql(a, params)} {_BOOL_SQL[op]} {compile_sql(b, params)})"
    if op == "case":
        const = _resolve_const(expr["on"], params)
        if const is not None:
            for match, branch in expr["when"]:
                if _matches(const, match):
                    return compile_sql(branch, params)
            if expr.get("else") is not None:
                return compile_sql(expr["else"], params)
            raise CalcIRError(f"case on constant {const!r} matched no branch and has no else")
        on_sql = compile_sql(expr["on"], params)
        whens = " ".join(
            f"WHEN {on_sql} = {compile_sql(_lit(match), params)} THEN {compile_sql(branch, params)}"
            for match, branch in expr["when"]
        )
        else_sql = f" ELSE {compile_sql(expr['else'], params)}" if expr.get("else") is not None else ""
        return f"CASE {whens}{else_sql} END"
    raise CalcIRError(f"unsupported op: {op!r}")


def compile_pandas(expr: Expr, params: Params) -> Callable[[pd.DataFrame], Any]:
    """Compile an Expr to a function ``df -> Series`` (or a plain scalar
    function for a purely-constant expr — the caller broadcasts it)."""
    op = expr["op"]
    if op == "col":
        name = expr["name"]
        return lambda df: df[name]
    if op == "lit":
        v = expr["value"]
        return lambda df: v
    if op == "param":
        if expr["name"] not in params:
            raise CalcIRError(f"unresolved parameter: {expr['name']!r}")
        v = params[expr["name"]]
        return lambda df: v
    if op in _ARITH_PD:
        fa = compile_pandas(expr["args"][0], params)
        fb = compile_pandas(expr["args"][1], params)
        fn = _ARITH_PD[op]
        return lambda df: fn(fa(df), fb(df))
    if op in _COMPARE_PD:
        fa = compile_pandas(expr["args"][0], params)
        fb = compile_pandas(expr["args"][1], params)
        fn = _COMPARE_PD[op]

        def _run_compare(df: pd.DataFrame):
            a, b = fa(df), fb(df)
            a, b = _coerce_compare_operands(a, b)
            return fn(a, b)

        return _run_compare
    if op in _BOOL_PD:
        fa = compile_pandas(expr["args"][0], params)
        fb = compile_pandas(expr["args"][1], params)
        fn = _BOOL_PD[op]
        return lambda df: fn(fa(df), fb(df))
    if op == "case":
        const = _resolve_const(expr["on"], params)
        if const is not None:
            for match, branch in expr["when"]:
                if _matches(const, match):
                    return compile_pandas(branch, params)
            if expr.get("else") is not None:
                return compile_pandas(expr["else"], params)
            raise CalcIRError(f"case on constant {const!r} matched no branch and has no else")
        on_fn = compile_pandas(expr["on"], params)
        branches = [(match, compile_pandas(branch, params)) for match, branch in expr["when"]]
        else_fn = compile_pandas(expr["else"], params) if expr.get("else") is not None else None

        def _run(df: pd.DataFrame) -> pd.Series:
            on_val = on_fn(df)
            conditions = [on_val.astype(str) == str(match) for match, _ in branches]
            choices = [fn(df) for _, fn in branches]
            default = else_fn(df) if else_fn is not None else np.nan
            return pd.Series(np.select(conditions, choices, default=default), index=df.index)

        return _run
    raise CalcIRError(f"unsupported op: {op!r}")
