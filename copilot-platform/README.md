# Copilot Platform — base chat shell (Part A)

The `titan_copilot` base architecture, standalone: one chat system that many
pluggable agents (Migration Buddy, Data Exploration, …) share. This is **Part C
step 1** from [`../COPILOT_PLATFORM_ARCHITECTURE.md`](../COPILOT_PLATFORM_ARCHITECTURE.md):
conversations/messages, `/completions` SSE, the LangGraph `agent_node ⇄ tools_node`
loop, and a control plane — with the A4 schema verbatim.

## What's here (maps to the architecture doc)

| Doc | Code |
|---|---|
| A1 layers | `main.py` (API) · `completion.py` (command) · `agent/graph.py` (LangGraph) · `control.py` (Redis/in-mem gates) |
| A2 routes | `routers/conversations.py`, `routers/completions.py` |
| A3 lifecycle | `completion.py::GenerateCompletionCommand.stream()` |
| A4 schema | `models.py` (`copilot_conversations`, `copilot_messages`) — verbatim |
| A5 turn model | 4 rows/turn sharing `run_id`, persisted in `completion.py` |
| A6 MCP tools | `agent/tools.py` (local stub now; MCP-discovered in Part C step 3) |
| B1/B2 plugins | `agent/registry.py` — `agent_type` → plugin |

**Deviation from the reference, by design:** the reference is Flask + CQRS +
a daemon-thread/Queue async↔sync bridge, needed only because it was embedded in
Superset's sync Flask app. Standalone we use **FastAPI (async-native)** so
LangGraph, SSE, and SQLAlchemy async run on one loop — the bridge disappears.
The CQRS *shape* (`GenerateCompletionCommand`, `ExecutionController`) and the A4
schema are kept.

## Run

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # optional
export COPILOT_FAKE_LLM=true  # run offline with no API key; else set ANTHROPIC_API_KEY
python smoke.py               # end-to-end: create chat -> stream completion -> read history
# or serve it:
uvicorn app.main:app --reload
```

With a real key: `unset COPILOT_FAKE_LLM; export ANTHROPIC_API_KEY=sk-...` (defaults to `claude-opus-5`).

## Tools — the local Superset MCP server (A6)

The `tools_node` discovers tools from Superset's built-in MCP server
(`superset mcp run`, streamable-http, port 5008) via `langchain-mcp-adapters`
(`app/agent/mcp_tools.py`). Superset's MCP uses a **tool-search** interface —
it exposes `search_tools` + `call_tool` (plus `health_check`, `get_instance_info`);
the agent searches for the right tool (datasets/charts/dashboards/schema/…) then
calls it. If the MCP server is unreachable, the copilot falls back to the local
stub tool, so it still runs offline. Config: `COPILOT_MCP_ENABLED`, `COPILOT_MCP_URL`.

## The Superset chat extension (`superset-extension/`)

A Module-Federation extension that registers our copilot as the active chat
(`chat.registerChat`, SIP-214). Its Panel streams from this backend. Override the
backend URL at runtime with `window.__COPILOT_BASE_URL__`.

## Full local bring-up

```bash
# 1. Superset MCP server (in the running superset container), reachable on 5008
docker exec -d superset-superset-light-1 \
  sh -c '/app/.venv/bin/superset mcp run --host 0.0.0.0 --port 5008 &'
#    (publish 5008 to the host — compose port map or `docker run -p` — so the
#     copilot on the host can reach http://localhost:5008/mcp/)

# 2. Copilot backend
cd copilot-platform && source .venv/bin/activate
export ANTHROPIC_API_KEY=sk-...        # or COPILOT_FAKE_LLM=true
uvicorn app.main:app --port 8000

# 3. Chat extension (dev loop)
cd superset-extension/frontend && npm install && npm run start   # webpack dev server :3000
#    enable in the superset container config: ENABLE_EXTENSIONS=True,
#    LOCAL_EXTENSIONS=[/path/to/superset-extension]; run `superset-extensions dev`
```

Then open Superset (`:9001`/`:8088`) → the 💬 button (bottom-right) → chat streams
from the copilot, which calls the real Superset MCP tools.

## Not yet built

Real JWT/RBAC (dev principal for now) · Postgres/Redis (SQLite + in-mem defaults) ·
LLM-written titles · capability-filtering MCP tools per agent · Migration/Exploration
agent graphs.
