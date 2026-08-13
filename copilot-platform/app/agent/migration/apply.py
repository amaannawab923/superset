"""Apply verified/flagged tiles to real Superset objects via MCP tools
(A6 tool layer) — called deterministically from Python, not left to the LLM
to decide, same "pre-fetch, don't make the LLM search" principle as the
earlier tool-selection-latency work on this project. Every call here goes
through the same `call_tool` proxy the chat agent itself uses, so RBAC and
event-logging on the Superset side apply exactly as they would to an
LLM-initiated call.
"""
from __future__ import annotations

import json
import logging
import re
import uuid

import pandas as pd
from langchain_core.tools import BaseTool

from .parsing import ChartPlan
from .verify import _bin_sql_expr, _categorical_bin_sql_expr, _dim_sql_expr, _measure_sql_expr

logger = logging.getLogger(__name__)

_UNTRUSTED_OPEN = "<UNTRUSTED-CONTENT>"
_UNTRUSTED_CLOSE = "</UNTRUSTED-CONTENT>"


def _strip_untrusted_wrapper(value: str) -> str:
    """Superset's MCP wraps free-text string fields (e.g. a chart's name) in
    <UNTRUSTED-CONTENT> delimiters as a prompt-injection defense (see
    superset/mcp_service/utils/sanitization.py) — same helper as
    claude_sdk_llm.py's artifact handling, duplicated here rather than
    imported since apply.py calls tools directly, not through that LLM
    response path."""
    text = value.strip()
    if text.startswith(_UNTRUSTED_OPEN) and text.endswith(_UNTRUSTED_CLOSE):
        text = text[len(_UNTRUSTED_OPEN) : -len(_UNTRUSTED_CLOSE)]
    return text.strip()


_AGG_SQL = {
    "Sum": "SUM", "Avg": "AVG", "Count": "COUNT",
    "CountD": "COUNT_DISTINCT", "Min": "MIN", "Max": "MAX",
}
_VIZ_CHART_TYPE = {
    "bar": ("xy", "bar"),
    "line": ("xy", "line"),
    "area": ("xy", "area"),
    "pie": ("pie", None),
    "big_number": ("big_number", None),
    "table": ("table", None),
}
_FILTER_OP = {"in": "IN"}
_GRID_COLUMN_COUNT = 12


def _unwrap(result: object) -> dict | None:
    """Normalize a call_tool response to a plain dict.

    The langchain_mcp_adapters proxy returns a list of MCP content blocks —
    ``[{"type": "text", "text": "<json>", "id": ...}, ...]`` — even for a
    single-value tool result; this is the actual shape observed live
    against the running MCP server, not a string or a bare dict."""
    if isinstance(result, list):
        for block in result:
            text = block.get("text") if isinstance(block, dict) else getattr(block, "text", None)
            if isinstance(text, str):
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    continue
        return None
    if isinstance(result, dict):
        return result
    if isinstance(result, str):
        try:
            return json.loads(result)
        except json.JSONDecodeError:
            return None
    content = getattr(result, "content", None)
    if isinstance(content, str):
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return None
    return None


def _safe_table_name(workbook_name: str) -> str:
    slug = re.sub(r"[^a-z0-9_]+", "_", workbook_name.lower()).strip("_")
    return f"mig_{slug}"[:60]


async def ensure_dataset(
    call_tool: BaseTool,
    primary: pd.DataFrame,
    workbook_name: str,
    database_id: int,
    tiles: list[ChartPlan] = (),
    schema: str = "public",
) -> int | None:
    """Load the workbook's primary extract table into Superset once — every
    tile's chart queries this same dataset with its own filters/metrics,
    the same way a real Superset dashboard's charts share one dataset.

    ``tiles`` (the tiles actually being applied) drives a second step: a
    bin/categorical-bin dim's verified FLOOR/CASE SQL — and, the same way,
    a Tableau-Analyst-resolved calc-field dim's SQL (see analyst.py) —
    can't ride as an adhoc dimension expression on generate_chart — the API
    rejects sql_expression on anything but a metric ("Use 'name' for
    dimension columns", confirmed live) — so both are materialized as real
    columns via create_virtual_dataset, reusing the exact same SQL string
    verify.py already checked. A resolved calc-field *measure* doesn't need
    this: generate_chart's metric ColumnRef accepts sql_expression directly
    (see _measure_ref). Skipped entirely when no tile needs one.
    """
    table_name = _safe_table_name(workbook_name)
    result = await call_tool.ainvoke(
        {
            "name": "create_dataset_from_data",
            "arguments": {
                "request": {
                    "database_id": database_id,
                    "table_name": table_name,
                    "schema": schema,
                    "csv_content": primary.to_csv(index=False),
                    "if_exists": "replace",
                },
            },
        }
    )
    dataset = _unwrap(result)
    if not dataset or dataset.get("error"):
        logger.error("Migration Buddy: dataset load failed for %s: %s", table_name, dataset)
        return None
    physical_id = dataset.get("id")

    # Dedup by dim col name — several tiles commonly bin/group (or resolve
    # the same calc field on) the same source field.
    synthetic_cols: dict[str, dict] = {}
    resolved_dim_cols: dict[str, dict] = {}
    for tile in tiles:
        for d in tile["dims"]:
            if d.get("synthetic"):
                synthetic_cols[d["col"]] = d["synthetic"]
            elif d.get("resolved"):
                resolved_dim_cols[d["col"]] = d["resolved"]
    if not synthetic_cols and not resolved_dim_cols:
        return physical_id

    computed_parts = [
        f'{_bin_sql_expr(spec) if spec["kind"] == "bin" else _categorical_bin_sql_expr(spec)} AS "{label}"'
        for label, spec in synthetic_cols.items()
    ] + [
        f'{_dim_sql_expr({"resolved": resolved})} AS "{label}"'
        for label, resolved in resolved_dim_cols.items()
    ]
    computed = ", ".join(computed_parts)
    sql = f'SELECT *, {computed} FROM "{schema}"."{table_name}"'
    result = await call_tool.ainvoke(
        {
            "name": "create_virtual_dataset",
            "arguments": {
                "request": {
                    "database_id": database_id,
                    "sql": sql,
                    "dataset_name": f"{table_name}_computed",
                },
            },
        }
    )
    virtual = _unwrap(result)
    if not virtual or virtual.get("error"):
        logger.error(
            "Migration Buddy: computed-column virtual dataset failed for %s: %s",
            table_name, virtual,
        )
        return physical_id  # degrade to the raw dataset — bin/group tiles will fail to build, not crash the run
    return virtual.get("id", physical_id)


def _column_ref(col: str, agg: str | None = None) -> dict:
    ref = {"name": col}
    if agg:
        ref["aggregate"] = agg
    return ref


def _measure_ref(m: dict) -> dict:
    """A measure's ColumnRef for the actual chart — a plain name+aggregate
    for a physical column, or a full SQL aggregate expression for a
    calc-resolved measure (see analyst.py). generate_chart accepts
    sql_expression on a metric field (chart/schemas.py's ColumnRef:
    "Custom SQL aggregate expression for an adhoc metric... Metric-only")
    — unlike a dimension, a resolved measure doesn't need the dataset-
    materialization workaround bin/group and resolved dims need."""
    if m.get("resolved"):
        return {"sql_expression": _measure_sql_expr(m), "label": f'{m["agg"]}({m["col"]})'}
    return _column_ref(m["col"], _AGG_SQL[m["agg"]])


def _dim_ref(dim: dict) -> dict:
    """A dim's ColumnRef for the actual chart. generate_chart rejects
    sql_expression on a dimension field (confirmed live: "Use 'name' for
    dimension columns") — so a bin/categorical-bin dim is referenced by
    plain name here, on the assumption that ensure_dataset materialized it
    as a real column (via create_virtual_dataset, using this exact same
    verified SQL) in the dataset this chart is built against."""
    return _column_ref(dim["col"])


def _filter_configs(filters: list[dict]) -> list[dict]:
    out = []
    for f in filters:
        if f["kind"] == "in":
            out.append({"column": f["col"], "op": "IN", "value": f["members"]})
        elif f["kind"] == "range":
            r = f["range"]
            if r.get("min") is not None:
                out.append({"column": f["col"], "op": ">=", "value": float(r["min"])})
            if r.get("max") is not None:
                out.append({"column": f["col"], "op": "<=", "value": float(r["max"])})
    return out


def build_chart_config(tile: ChartPlan) -> dict:
    """Map a ChartPlan to the ChartConfig shape generate_chart accepts.
    Dims beyond the first become group_by/series — a reasonable heuristic
    for the shelves this pass supports (single-level GROUP BY), not a
    faithful reproduction of Tableau's own rows/cols shelf split."""
    chart_type, kind = _VIZ_CHART_TYPE.get(tile["viz_type"], ("table", None))
    metrics = [_measure_ref(m) for m in tile["measures"]]
    dims = [_dim_ref(d) for d in tile["dims"]]
    filters = _filter_configs(tile["filters"])

    if chart_type == "xy":
        config: dict = {"chart_type": "xy", "kind": kind, "y": metrics, "filters": filters}
        if dims:
            config["x"] = dims[0]
            if len(dims) > 1:
                config["group_by"] = dims[1:]
        return config
    if chart_type == "pie":
        return {
            "chart_type": "pie",
            "dimension": dims[0] if dims else _column_ref(tile["measures"][0]["col"]),
            "metric": metrics[0] if metrics else _column_ref(tile["measures"][0]["col"], "COUNT"),
            "filters": filters,
        }
    if chart_type == "big_number":
        return {"chart_type": "big_number", "metric": metrics[0], "filters": filters}
    return {"chart_type": "table", "columns": dims + metrics, "filters": filters}


async def apply_tile(call_tool: BaseTool, tile: ChartPlan, dataset_id: int) -> dict | None:
    """Create a real, saved Superset chart for a GREEN/YELLOW tile. Returns
    the chart's ChartInfo dict (with "id") on success, None on failure —
    callers should treat a build failure as effectively RED for the
    fidelity report: a verified translation nobody can see isn't useful."""
    config = build_chart_config(tile)
    result = await call_tool.ainvoke(
        {
            "name": "generate_chart",
            "arguments": {
                "request": {
                    "dataset_id": dataset_id,
                    "config": config,
                    "chart_name": tile["sheet"],
                    "save_chart": True,
                    "generate_preview": False,
                },
            },
        }
    )
    chart_response = _unwrap(result)
    if not chart_response or chart_response.get("error"):
        logger.warning(
            "Migration Buddy: chart build failed for %r: %s", tile["sheet"], chart_response
        )
        return None
    chart = chart_response.get("chart")
    if chart and isinstance(chart.get("slice_name"), str):
        chart["slice_name"] = _strip_untrusted_wrapper(chart["slice_name"])
    return chart


def _generate_id(prefix: str) -> str:
    # Matches the frontend's nanoid-style component-id pattern
    # (superset/mcp_service/dashboard/constants.py::generate_id) — a
    # separate process (copilot-platform), so reimplemented rather than
    # imported cross-service.
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def build_position_json(applied: list[tuple[ChartPlan, dict]], dashboard_title: str) -> dict:
    """A ROW > COLUMN > CHART position_json mirroring the source workbook's
    own layout (grouped by row_index, widths from gw) instead of
    generate_dashboard's default fixed 2-per-row auto-grid."""
    rows: dict[int, list[tuple[ChartPlan, dict]]] = {}
    for tile, chart in applied:
        rows.setdefault(tile["row_index"], []).append((tile, chart))

    layout: dict = {}
    row_ids = []
    for row_index in sorted(rows):
        row_tiles = rows[row_index]
        row_id = _generate_id("ROW")
        row_ids.append(row_id)
        column_keys = []
        for tile, chart in row_tiles:
            chart_id = chart["id"]
            chart_key = f"CHART-{chart_id}"
            column_key = _generate_id("COLUMN")
            column_keys.append(column_key)
            layout[chart_key] = {
                "children": [],
                "id": chart_key,
                "meta": {
                    "chartId": chart_id,
                    "height": tile["gh"],
                    "sliceName": chart.get("slice_name") or tile["sheet"],
                    "uuid": str(chart.get("uuid") or f"chart-{chart_id}"),
                    "width": tile["gw"],
                },
                "parents": ["ROOT_ID", "GRID_ID", row_id, column_key],
                "type": "CHART",
            }
            layout[column_key] = {
                "children": [chart_key],
                "id": column_key,
                "meta": {"background": "BACKGROUND_TRANSPARENT", "width": tile["gw"]},
                "parents": ["ROOT_ID", "GRID_ID", row_id],
                "type": "COLUMN",
            }
        layout[row_id] = {
            "children": column_keys,
            "id": row_id,
            "meta": {"background": "BACKGROUND_TRANSPARENT"},
            "parents": ["ROOT_ID", "GRID_ID"],
            "type": "ROW",
        }

    layout["GRID_ID"] = {"children": row_ids, "id": "GRID_ID", "parents": ["ROOT_ID"], "type": "GRID"}
    layout["ROOT_ID"] = {"children": ["GRID_ID"], "id": "ROOT_ID", "type": "ROOT"}
    layout["DASHBOARD_VERSION_KEY"] = "v2"
    return layout


async def assemble_dashboard(
    call_tool: BaseTool, applied: list[tuple[ChartPlan, dict]], dashboard_title: str
) -> dict | None:
    """generate_dashboard over every successfully-applied tile, with an
    explicit position_json so the migrated dashboard mirrors the source
    layout instead of the tool's default fixed grid."""
    if not applied:
        return None
    chart_ids = [chart["id"] for _tile, chart in applied]
    position_json = build_position_json(applied, dashboard_title)
    result = await call_tool.ainvoke(
        {
            "name": "generate_dashboard",
            "arguments": {
                "request": {
                    "chart_ids": chart_ids,
                    "dashboard_title": dashboard_title,
                    "position_json": position_json,
                },
            },
        }
    )
    dashboard_response = _unwrap(result)
    if not dashboard_response or dashboard_response.get("error"):
        logger.error("Migration Buddy: dashboard assembly failed: %s", dashboard_response)
        return None
    dashboard = dashboard_response.get("dashboard")
    if dashboard and isinstance(dashboard.get("dashboard_title"), str):
        dashboard["dashboard_title"] = _strip_untrusted_wrapper(dashboard["dashboard_title"])
    return dashboard
