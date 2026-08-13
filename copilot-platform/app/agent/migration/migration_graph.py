"""Top-level Migration Buddy orchestration.

    ingest -> plan -> (per-tile verify, one at a time) -> apply GREEN/YELLOW
        -> assemble -> report

A plain async generator, not a LangGraph StateGraph: the per-tile fan-out
and progress narration are more naturally a linear async function than a
sequence of StateGraph node "updates", and the other usual reason to reach
for StateGraph here — checkpointed human-in-the-loop review of RED tiles —
is explicitly out of scope for this pass (see
MIGRATION_BUDDY_ARCHITECTURE.md's phased roadmap: RED tiles are flagged and
skipped, not escalated to a human interrupt yet). The per-tile verify step
itself *is* a real LangGraph graph (verify.py); this module is the
orchestration around it.
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from ...config import get_settings
from ..mcp_tools import load_tools
from . import apply, parsing, verify

logger = logging.getLogger(__name__)


async def run_migration(
    twbx_path: str, workbook_display_name: str
) -> AsyncIterator[dict[str, Any]]:
    """Yields progress dicts as the migration proceeds:
    {"stage": "parsing"|"planning"|"verifying"|"applying"|"assembling"|"done"|"error",
     "tile": str | None, "verdict": "GREEN"|"YELLOW"|"RED" | None, "detail": str}

    The terminal event is either {"stage": "error", "detail": ...} or
    {"stage": "done", "detail": ..., "report": {"GREEN": n, "YELLOW": n,
    "RED": n}, "dashboard": {...} | None}.
    """
    yield {"stage": "parsing", "detail": f"Unpacking {workbook_display_name}…"}
    try:
        root, inst, formulas, frames, primary = parsing.load_workbook(twbx_path)
    except Exception as exc:  # noqa: BLE001 — a bad upload must flag, not crash the turn
        logger.exception("Migration Buddy: failed to parse workbook")
        yield {"stage": "error", "detail": f"Could not parse this workbook: {exc}"}
        return

    if primary is None:
        yield {
            "stage": "error",
            "detail": (
                "This workbook has no packaged data extract (a live/external "
                "connection) — Migration Buddy needs a packaged .hyper extract "
                "to verify numbers against. In Tableau, try File → Export "
                "Packaged Workbook first."
            ),
        }
        return

    dashboard_el = parsing.pick_target_dashboard(root)
    if dashboard_el is None:
        yield {"stage": "error", "detail": "No dashboard found in this workbook."}
        return
    dashboard_name = dashboard_el.get("name") or "Dashboard"

    tiles = parsing.plan_tiles(root, dashboard_el, inst, formulas, frames)
    yield {
        "stage": "planning",
        "detail": f'Found {len(tiles)} tile(s) on "{dashboard_name}".',
    }
    if not tiles:
        yield {
            "stage": "error",
            "detail": f'"{dashboard_name}" has no chart tiles to migrate.',
        }
        return

    tools = await load_tools()
    call_tool = next((t for t in tools if t.name == "call_tool"), None)
    if call_tool is None:
        yield {
            "stage": "error",
            "detail": "Superset's tools aren't reachable right now — try again shortly.",
        }
        return

    database_id = get_settings().copilot_migration_database_id
    # Only SIMPLE_AGG-classified tiles can ever reach GREEN/YELLOW and get
    # built — pass just those so ensure_dataset only materializes the
    # bin/categorical-bin columns actually needed by tiles that have a
    # chance of shipping, not every bin defined anywhere in the workbook.
    buildable = [t for t in tiles if t["klass"] == "SIMPLE_AGG"]
    dataset_id = await apply.ensure_dataset(
        call_tool, primary, workbook_display_name, database_id, buildable
    )
    if dataset_id is None:
        yield {
            "stage": "error",
            "detail": "Could not load the workbook's data into Superset.",
        }
        return

    tile_graph = verify.build_tile_graph(primary)
    applied: list[tuple[dict, dict]] = []
    tally = {"GREEN": 0, "YELLOW": 0, "RED": 0}

    for tile in tiles:
        yield {
            "stage": "verifying", "tile": tile["sheet"], "verdict": None,
            "detail": f'Verifying "{tile["sheet"]}"…',
        }
        out = await tile_graph.ainvoke({"tile": tile})
        verdict = out["verdict"]
        tally[verdict] += 1
        yield {
            "stage": "verifying", "tile": tile["sheet"], "verdict": verdict,
            "detail": out["reason"],
        }

        if verdict not in ("GREEN", "YELLOW"):
            continue

        yield {
            "stage": "applying", "tile": tile["sheet"], "verdict": verdict,
            "detail": f'Building "{tile["sheet"]}"…',
        }
        chart = await apply.apply_tile(call_tool, tile, dataset_id)
        if chart:
            applied.append((tile, chart))
            yield {
                "stage": "applying", "tile": tile["sheet"], "verdict": verdict,
                "detail": f'Built chart "{chart.get("slice_name") or tile["sheet"]}".',
            }
        else:
            tally[verdict] -= 1
            tally["RED"] += 1
            yield {
                "stage": "applying", "tile": tile["sheet"], "verdict": "RED",
                "detail": f'Verified but could not build a chart for "{tile["sheet"]}" '
                "— skipping.",
            }

    if not applied:
        yield {
            "stage": "done",
            "detail": "No tiles could be verified and built — nothing to assemble.",
            "report": tally,
            "dashboard": None,
        }
        return

    yield {
        "stage": "assembling", "tile": None, "verdict": None,
        "detail": f"Assembling {len(applied)} chart(s) into a dashboard…",
    }
    dashboard = await apply.assemble_dashboard(
        call_tool, applied, f"{dashboard_name} (migrated from {workbook_display_name})"
    )
    if dashboard is None:
        yield {
            "stage": "error",
            "detail": "Charts were built but the dashboard could not be assembled.",
        }
        return

    yield {
        "stage": "done",
        "detail": (
            f'{tally["GREEN"]} verified, {tally["YELLOW"]} unverified-but-built, '
            f'{tally["RED"]} flagged (of {len(tiles)} tiles).'
        ),
        "report": tally,
        "dashboard": dashboard,
    }
