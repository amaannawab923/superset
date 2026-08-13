"""Free-form Migration Buddy — a real coding agent (Claude Agent SDK with
Bash/Read/Write, not a fixed IR/compiler) reads the workbook and Superset's
REST API directly, using its own judgment for every translation.

Proven out as a one-off POC before this module existed: on MerchandiseSales
— a workbook the deterministic pipeline (parsing.py/verify.py/apply.py/
calc_ir.py) couldn't get a single tile through on, blocked by table calcs,
date functions, and a shared date-range filter it had no vocabulary for —
a free-form agent built 23 real charts across all 22 tiles. It caught a
genuine Superset bug along the way (TEMPORAL_RANGE's half-open interval
silently undercounting) and a misleading calc-field label (a field named
"...Clothing" that actually filters on Ornaments) by reading the real
formulas and data rather than trusting a symbol name. This module is the
production version of that POC: same idea, wired into the actual
migration flow instead of a one-off Task spawn.

Deliberate trade-off, made explicit rather than silently defaulted into:
this path has NO deterministic oracle gate. "Verified" here means the
agent checked its own work if and when it chose to (it did, in the POC —
recomputing pie-chart totals in pandas before shipping) — there is no
independent, mechanical guarantee the way verify.py's data-oracle diff
gives the classify()-driven pipeline. What this buys instead: real
judgment on calc chains, table calcs, and date functions the narrow
calc_ir vocabulary either can't express or needs hand-written compiler
support for every new pattern (see docs/MIGRATION_BUDDY_MULTI_AGENT.md for
why that doesn't scale). The two pipelines are not mutually exclusive —
this one is a separate, explicit choice, not a replacement.
"""
from __future__ import annotations

import logging
import shutil
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_COPILOT_PLATFORM_ROOT = Path(__file__).resolve().parents[3]


def _tool_summary(name: str, tool_input: dict[str, Any]) -> str:
    """A one-line, human-readable summary of a tool call for progress
    narration — not every tool's full input (a Bash command can be long,
    a Write's content can be huge), just enough for a user watching the
    trace to follow along step by step, per the explicit ask for
    visibility into "each and every step", not just a final report."""
    if name == "Bash":
        cmd = str(tool_input.get("command", "")).strip().replace("\n", " ")
        return cmd[:160] + ("…" if len(cmd) > 160 else "")
    if name in ("Write", "Edit"):
        return f'writing {tool_input.get("file_path", "?")}'
    if name == "Read":
        return f'reading {tool_input.get("file_path", "?")}'
    return name


_SYSTEM_PROMPT_TEMPLATE = """\
You are acting as a combined "Tableau expert + Superset expert". Your job: \
freely, tile-by-tile, recreate as much of a real Tableau dashboard as you \
reasonably can as real charts + a dashboard in a live Apache Superset \
instance, hitting Superset's REST API directly — using your own judgment \
for every SQL/calc translation, not a fixed rule engine. Skipping a tile \
you can't confidently translate (and saying why) is much better than \
guessing and shipping something wrong.

## The workbook

`{twbx_path}`. Here is a reconnaissance pass's description of it (trust it \
as your map of what exists, but verify details yourself against the real \
file/data — don't take a label like "summed metric" at face value, go read \
the actual calc formula):

---
{workbook_context}
---

## Reading the workbook (real formulas + real extract data)

From `{cwd}`, using `.venv/bin/python3` (has pandas/pantab/duckdb \
installed):
```python
import sys; sys.path.insert(0, '.')
from app.agent.migration import tableau_parse as tp
root, inst, formulas, frames = tp.load_workbook('{twbx_path}')
primary = max(frames.values(), key=lambda d: d.shape[1])  # the packaged extract as a real pandas DataFrame
# formulas: dict[calc_id -> Tableau formula string]
# root.iter('worksheet'), root.iter('dashboard') — full .twb XML for shelf/mark details on a specific tile
# tp.parameter_value(root, '[Parameters].[Parameter 1]') -> the parameter's current live value as a string
```
Full freedom here — read whatever XML/formula/data you need. No fixed IR, \
no vocabulary constraint; write whatever SQL correctly expresses what you \
find.

## Superset's REST API — auth flow

Base URL `{superset_base_url}`. Use a `requests.Session()` so cookies \
persist — the CSRF check needs both the token AND the session cookie from \
when you fetched it.
```python
import requests
s = requests.Session()
r = s.post("{superset_base_url}/api/v1/security/login", json={{
    "username": "{admin_user}", "password": "{admin_password}", "provider": "db", "refresh": True,
}})
token = r.json()["access_token"]
s.headers["Authorization"] = f"Bearer {{token}}"
csrf = s.get("{superset_base_url}/api/v1/security/csrf_token/").json()["result"]
s.headers["X-CSRFToken"] = csrf
# now s.post(...)/s.get(...) with this session works for both reads and mutations
```
GET works with just the Bearer header; POST/PUT/DELETE need the CSRF \
header too, and the CSRF token is only valid together with the session \
cookie it was issued alongside — don't fetch it with a fresh session.

Database to use: `database_id: {database_id}`, `schema: "public"`.

## Key endpoints you'll need

- **Load the extract as a dataset**: `POST /api/v1/database/{database_id}/upload/` \
— multipart form (not JSON): fields `table_name`, `schema`, `file` (the CSV \
bytes — write `primary.to_csv(index=False)` to a temp file first), \
`already_exists` (use `"replace"`). After upload, \
`GET /api/v1/dataset/?q=(filters:!((col:table_name,opr:eq,value:'<name>')))` \
to find the created dataset's id.
- **A computed/virtual dataset** (for a calc-derived DIMENSION that needs to \
exist as a real column — native charts can't reference an inline SQL \
expression for a dimension, only for a metric): `POST /api/v1/dataset/` \
with a `sql` field (a `SELECT *, <expr> AS "<label>" FROM "public"."<table>"` \
query) instead of pointing at a physical table.
- **Create a chart**: `POST /api/v1/chart/` — body needs `slice_name`, \
`viz_type`, `datasource_id`, `datasource_type: "table"`, and `params` (a \
**JSON-encoded string**, not a nested object). The exact shape of `params` \
varies by `viz_type` — fetch a REAL existing chart of the viz_type you want \
as a template: \
`GET /api/v1/chart/?q=(filters:!((col:viz_type,opr:eq,value:'<viz_type>')),page_size:3)`, \
inspect its `params`, adapt it. Common `viz_type` values: \
`echarts_timeseries_bar`, `echarts_timeseries_line`, `echarts_area`, \
`pie`, `big_number_total`, `table`. For a metric built from a custom SQL \
expression (allowed on a metric, not a dimension), use \
`"expressionType": "SQL", "sqlExpression": "<sql>"` instead of \
`"expressionType": "SIMPLE"`.
- **Create the dashboard**: `POST /api/v1/dashboard/` — body needs \
`dashboard_title`; inspect `GET /api/v1/dashboard/<existing_id>` on a real \
dashboard if you need the shape for adding charts/tabs.
- **Sanity-check your own numbers** — optional but recommended: run your \
own SQL/pandas against the extract locally before shipping a chart, to \
catch an obviously wrong translation before it ships. You decide how much.

## Picking a chart type — reference, not a rule

A prior migration run got the underlying data right on nearly every tile \
but lost accuracy specifically on chart-*type* choice. Use this as a \
starting point (learned from real testing on real workbooks), then use \
your own judgment where a tile doesn't fit cleanly — this is guidance to \
ground you, not a rigid mapping to follow blindly:

- Tableau mark `Pie` → Superset `pie`.
- Tableau mark `Line` → `echarts_timeseries_line`.
- Tableau mark `Area` → `echarts_area`.
- Tableau mark `Bar`/`GanttBar` with a dimension on rows/cols → \
`echarts_timeseries_bar`; with NO dimension (just one or more raw \
aggregates) → `big_number_total`.
- One or more measures, zero dimensions, any other mark → `big_number_total`.
- One or more measures with a dimension, mark doesn't clearly imply a \
type → `echarts_timeseries_bar` as a safe default.
- Many dimension-like fields, few/no real aggregates (a raw record list — \
Tableau marks `Circle`/`Square` are common for this) → `table`.
- Two continuous measures with NO dimension, or an identity dimension from \
the Detail shelf only → this is Tableau's scatter-plot shape. **Known \
landmine**: Superset's `echarts_timeseries_scatter` treats its x-axis as a \
plain grouping column, not an aggregated metric — it CANNOT represent two \
independently-aggregated measures the way Tableau's scatter can. If you \
pick it for a true 2-aggregated-measure scatter, the built chart will not \
actually show what you verified, even though it "looks" like a scatter \
chart. Prefer `table` (dims + both aggregated measures) for this shape \
unless you've confirmed Superset's scatter viz can actually express what \
the tile needs.
- Two measures that look like `Avg(Latitude)`/`Avg(Longitude)` (or \
similar lat/long pair), no other dimension → this is a map. Check what \
geo viz_types this Superset instance actually supports (e.g. \
`deck_scatter`) by inspecting existing charts or the dataset's columns \
before committing to one.

If you're unsure, fetch 2-3 real existing charts of a candidate viz_type \
(`GET /api/v1/chart/?q=(filters:!((col:viz_type,opr:eq,value:'<type>')))`) \
and see if their shape (metrics/dims) resembles what you're building — a \
real working example beats guessing at the schema.

If you get a validation error, READ it — Superset's API error messages are \
usually specific about which field/shape is wrong. Iterate rather than \
giving up on a tile after one failed attempt, but don't burn excessive \
time on any single tile — if it's genuinely not working after a couple of \
tries, skip it and move on.

## What to do

1. Auth, then load the primary extract as a base dataset via the upload \
endpoint.
2. Go tab by tab, tile by tile (skip decoration/label-only tiles). For \
each real chart tile: understand what it computes (read the calc chain, \
check real shelf/mark XML if useful), decide the right Superset chart \
type + SQL, create it. Materialize calc-derived dimensions as virtual-\
dataset columns first if needed.
3. Assemble what you built into a dashboard (one, or one per tab — your \
call).

## What to report back (your final message)

End with a section titled exactly `## Report` containing:
- The dashboard(s) you created: title, id, URL.
- Every chart you built: name, id, one-line note on the SQL/logic used.
- Every tile you skipped and why, one sentence each.
- Anything you're unsure about — surfacing doubt beats false confidence, \
this is being evaluated for accuracy afterward.
"""


async def run_freeform_migration(
    twbx_path: str,
    workbook_display_name: str,
    database_id: int,
    superset_base_url: str,
    admin_user: str,
    admin_password: str,
) -> AsyncIterator[dict[str, Any]]:
    """Same progress-dict shape as migration_graph.run_migration
    ({"stage", "tile", "verdict", "detail"}) so completion.py's SSE
    forwarding needs no changes to use this path instead — the terminal
    event is {"stage": "done", "detail": ..., "report": None,
    "dashboard": None} (this path has no structured GREEN/YELLOW/RED
    tally or single dashboard artifact the way the deterministic pipeline
    does; the agent's own "## Report" section in `detail` is the report).
    """
    from claude_agent_sdk import (
        AssistantMessage,
        ClaudeAgentOptions,
        ResultMessage,
        TextBlock,
        ToolUseBlock,
        query,
    )

    from . import parsing, tableau_parse as tp

    yield {"stage": "parsing", "detail": f"Unpacking {workbook_display_name}…"}
    try:
        root, inst, formulas, frames = tp.load_workbook(twbx_path)
        tabs = parsing.describe_workbook(root, inst, formulas)
        workbook_context = parsing.format_tabs_context(tabs)
    except Exception as exc:  # noqa: BLE001 — a bad upload must flag, not crash the turn
        logger.exception("Migration Buddy (free-form): failed to parse workbook")
        yield {"stage": "error", "detail": f"Could not parse this workbook: {exc}"}
        return

    # The agent works from its own copy — never the original upload path —
    # so nothing it does (including a stray overwrite) can touch the
    # user's actual uploaded file.
    scratch_dir = tempfile.mkdtemp(prefix="migration_freeform_")
    scratch_twbx = str(Path(scratch_dir) / Path(twbx_path).name)
    shutil.copy2(twbx_path, scratch_twbx)

    prompt = f"Migrate the Tableau workbook at {scratch_twbx} into Superset."
    system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(
        twbx_path=scratch_twbx,
        workbook_context=workbook_context,
        cwd=str(_COPILOT_PLATFORM_ROOT),
        superset_base_url=superset_base_url,
        admin_user=admin_user,
        admin_password=admin_password,
        database_id=database_id,
    )
    options = ClaudeAgentOptions(
        allowed_tools=["Bash", "Read", "Write"],
        permission_mode="bypassPermissions",  # no human in the loop to approve each call
        setting_sources=[],
        cwd=str(_COPILOT_PLATFORM_ROOT),
        system_prompt=system_prompt,
    )

    yield {
        "stage": "planning",
        "detail": f'Handing "{workbook_display_name}" to the free-form migration agent…',
    }

    final_text = ""
    try:
        async for msg in query(prompt=prompt, options=options):
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock) and block.text.strip():
                        yield {
                            "stage": "building", "tile": None, "verdict": None,
                            "detail": block.text.strip(),
                        }
                    elif isinstance(block, ToolUseBlock):
                        yield {
                            "stage": "building", "tile": None, "verdict": None,
                            "detail": f"[{block.name}] {_tool_summary(block.name, block.input)}",
                        }
            elif isinstance(msg, ResultMessage):
                final_text = msg.result or final_text
    except Exception as exc:  # noqa: BLE001 — an agent-side failure must flag, not crash the turn
        logger.exception("Migration Buddy (free-form): agent run failed")
        yield {"stage": "error", "detail": f"The migration agent hit an error: {exc}"}
        return
    finally:
        shutil.rmtree(scratch_dir, ignore_errors=True)

    yield {
        "stage": "done",
        "detail": final_text or "The agent finished but returned no final report.",
        "report": None,
        "dashboard": None,
    }
