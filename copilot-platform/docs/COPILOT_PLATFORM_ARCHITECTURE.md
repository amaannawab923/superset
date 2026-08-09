# Copilot Platform Architecture — Migration Buddy + Data Exploration on one chat system

**The idea in one paragraph.** One chat system (the `titan_copilot` pattern below), *many pluggable
agents*. Migration Buddy is one agent pinned in the left rail; a Data Exploration agent is another.
From a single conversational surface the user can **migrate their Tableau dashboards** *and* **research/
analyze their data** — every agent shares the same LangGraph runtime, SSE streaming, conversation
persistence, artifact rendering, and MCP tool layer. Each agent is a **plugin**: it differs only in its
system prompt, its allowed tools, and its graph. The base architecture was already built for this — it
carries an `agent_type` field (DEFAULT / SQL_EXPERT / EXPERIMENTATION); we plug our agents into it.

---

# PART A — Base Architecture (reference: `titan_copilot`)

An agentic BI chatbot for Superset: a LangGraph agent that streams over SSE, backed by a
Flask/CQRS/Postgres/Redis backend, using **MCP** to reach a Titan MCP server that wraps REST APIs over
ClickHouse + Superset.

## A1 — System layers

```mermaid
flowchart TD
    B["BROWSER — React SPA<br/>ConversationList (sidebar) · ChatView (MessageList + MessageInput)<br/>SSE reader (fetch + ReadableStream) · ThoughtChain / tool-call timeline"]
    F["FLASK API LAYER<br/>routes @protect() (JWT + RBAC) · COPILOT_WS_ENABLED gate (404)<br/>request validation (Pydantic) · SSE response generator"]
    C["COMMAND LAYER (CQRS)<br/>GenerateCompletionCommand — captures JWT/user/flags, spawns daemon thread + Queue (async↔sync bridge)<br/>ExecutionController — Redis gates · cancel poll · time budget"]
    L["LANGGRAPH AGENT<br/>agent_node ⇄ tools_node (loop until no tool_calls)<br/>should_continue router · loop guards · checkpointer<br/>tool discovery (cached) · capability filter · per-tool limits"]
    LLM["LLM (streamed)<br/>completions · streamed tokens + usage/cost"]
    MCP["MCP / HTTP Client (mcp_client.py, OUR repo)<br/>list_tools() → tools/list (cached 300s)<br/>call_tool() · forwards Bearer JWT"]
    T["TITAN MCP SERVER (separate repo)<br/>FastMCP · each tool wraps a Titan REST API<br/>JWT re-verified + RBAC every call → ClickHouse · Superset"]
    PG["PostgreSQL<br/>copilot_conversations · copilot_messages<br/>(+ LangGraph checkpoints, optional) — durable source of truth"]
    R["Redis<br/>concurrency gates · cancel flags · tool cache<br/>circuit breaker · rate limit — fast, TTL, cross-pod"]
    B -->|REST + SSE| F --> C --> L
    L -->|stream LLM| LLM
    L -->|tool call| MCP -->|MCP protocol (JWT)| T
    C -->|persist msgs| PG
    C -.->|gates / cancel| R
```

**Layer responsibilities**

- **Browser (React SPA)** — conversation sidebar, chat view (message list + input), an **SSE reader**
  (`fetch` + `ReadableStream`), and a **ThoughtChain / tool-call timeline** that renders the agent's
  intermediate tool steps.
- **Flask API layer** — `@protect()` (JWT auth + RBAC), a feature-flag gate (`COPILOT_WS_ENABLED` →
  404 when off), **Pydantic** request validation, and the **SSE response generator**.
- **Command layer (CQRS)** —
  - `GenerateCompletionCommand`: captures JWT / user / feature-flags **while the Flask context is
    alive**, then spawns a **daemon thread + Queue** as the **async↔sync bridge** (LangGraph is async;
    Flask/SQLAlchemy is sync).
  - `ExecutionController`: Redis concurrency gates, cancel polling, time budget.
- **LangGraph agent** — the `agent_node ⇄ tools_node` loop (repeat until the LLM emits no more
  `tool_calls`), a `should_continue` router, loop guards, a **checkpointer**, runtime **tool discovery**
  (cached), a **capability filter**, and **per-tool limits**.
- **LLM** — streamed token-by-token; usage + cost captured per turn.
- **MCP / HTTP client** — *we build only the client*; it discovers tools (`tools/list`, cached 300s) and
  executes them (`tools/call`), forwarding the user's `Bearer <JWT>` + workspace header.
- **Titan MCP server (separate repo)** — a FastMCP server that **already exists**; each `@mcp.tool()`
  is a thin wrapper over a Titan REST API, and it **re-verifies JWT + RBAC on every call** (the real
  gate). This is where ClickHouse/Superset actually get touched.
- **PostgreSQL** — durable source of truth: conversations + messages (+ optional LangGraph checkpoints).
- **Redis** — fast, TTL-based, cross-pod control plane: concurrency gates, cancel flags, tool cache,
  circuit breaker, rate limit.

## A2 — API routes (`prefix: /api/v1/copilot`)

| Method | Path | Purpose |
|---|---|---|
| POST | `/conversations` | Create a new (empty) chat; a title may be auto-generated later |
| GET | `/conversations` | List the user's chats (paginated, sorted by `last_message_at`) |
| GET | `/conversations/{id}` | Get one conversation's details |
| PATCH | `/conversations/{id}` | Rename / archive / pin (sets `title_source = USER`) |
| DELETE | `/conversations/{id}` | Soft-delete the chat (`status = DELETED`, kept for audit) |
| GET | `/conversations/{id}/messages` | Load message history (paginated, oldest-first) on resume |
| DELETE | `/conversations/{id}/messages/{mid}` | Soft-delete a single message |
| **POST** | **`/completions`** | ★ Stream an agent completion over SSE — runs the LangGraph loop |
| POST | `/chat/cancel` | Cancel an in-progress generation (writes a Redis cancel flag) |

## A3 — Request lifecycle

**A completion (`POST /completions`)**
1. User clicks Send → optimistic UI; `POST /completions {conversation_id, message}`.
2. `@protect()`: validate JWT, check `COPILOT_WS_ENABLED`, verify the user **owns** the chat.
3. `GenerateCompletionCommand.__init__` captures JWT / user / flags **while the Flask context is alive**.
4. Acquire the **Redis concurrency gate**; save the USER message to Postgres immediately.
5. Spawn a **daemon thread + new event loop**; the **SSE stream opens** to the browser.
6. Agent setup: MCP **tool discovery** (cached 300s) → **filter by capabilities** → wrap with limits.
7. `agent_node` streams LLM tokens → SSE `token` events render live.
8. `tool_calls?` → `tools_node` POSTs to MCP (JWT re-verified + RBAC) → `ToolMessage` → loop back.
9. no `tool_calls` → `'end'`; LangGraph checkpoint saved.
10. response guards → save ASSISTANT message → record token usage.
11. SSE: `usage`, `final`, `token_status`; **release the gate** (in a `finally`).
12. Frontend renders the answer + thought chain + any charts.

**A new chat (`POST /conversations`)**
1. User clicks **+ New Chat**. 2. `POST /conversations {agent_type}`. 3. `INSERT copilot_conversations
(title=NULL, status=ACTIVE, message_count=0)`. 4. Return `{id, title:null, status:active}`. 5. Frontend
opens an empty chat, focuses input. 6. After the first assistant reply, the LLM writes a 3–5 word title
(`title_source=SYSTEM`).

## A4 — Database schema (PostgreSQL)

### `copilot_conversations` — one row = one chat thread
| Column | Type | Purpose |
|---|---|---|
| `id` | UUID **PK** | Conversation id; also the chat's thread key |
| `user_id` | BIGINT **FK** | Owner (→ `ab_user.id`); per-user isolation |
| `workspace_id` | VARCHAR **IDX** | Tenant/workspace; row-level isolation |
| `thread_id` | VARCHAR **UK** | Links the chat to its **LangGraph checkpoint thread** |
| `title` | VARCHAR(255) | Sidebar display name |
| `title_source` | ENUM | SYSTEM (auto) or USER (renamed) — stops auto-overwrite of a user title |
| `agent_type` | ENUM | **DEFAULT / SQL_EXPERT / EXPERIMENTATION** — which persona is used |
| `status` | ENUM **IDX** | ACTIVE / ARCHIVED / DELETED — soft-delete lifecycle |
| `last_message_at` | TIMESTAMP **IDX** | Sidebar sort key (most-recent first) |
| `created_at` / `updated_at` / `deleted_at` | TIMESTAMP | created / modified / soft-delete (audit) |
| `message_count` | INT | Denormalized count for fast sidebar rendering |
| `metadata_json` | JSON | Extensible: pinned flag, model, context-window info |

### `copilot_messages` — one row = one message (**this is the conversation memory**)
| Column | Type | Purpose |
|---|---|---|
| `id` | UUID **PK** | Message id |
| `conversation_id` | UUID **FK** | Parent conversation |
| `workspace_id` | VARCHAR | Denormalized tenant id for fast filtering |
| `role` | ENUM | **USER / ASSISTANT / SYSTEM / TOOL** — who authored it |
| `content` | TEXT | Message text / assistant answer body |
| `tool_calls` | JSON | Array of `{id, tool_name, arguments}` the LLM requested this turn |
| `tool_call_id` | VARCHAR | For TOOL rows: which tool call this result answers |
| `run_id` | VARCHAR **IDX** | Groups every message produced in **one completion turn** |
| `status` | ENUM **IDX** | active / deleted (per-message soft-delete) |
| `artifacts` | JSON | **Charts / datasets / query-results rendered inline in the chat** |
| `prompt_tokens` / `completion_tokens` | INT | Billing & limits |
| `cost_usd` | DECIMAL | Dollar cost of this turn |
| `metadata_json` | JSON | is_error, reasoning_content, interrupted, stop_reason, … |
| `suggested_id` | VARCHAR | If the chat began from a suggested prompt, which one |
| `created_at` | TIMESTAMP **IDX** | Ordering key for oldest-first replay |

## A5 — The message model: one turn (worked example: *"Show me DAU for March"*)

All rows in a turn share `run_id` and `conversation_id`. A single turn is up to four rows:

1. **USER** — `role=USER`, `content="Show me DAU for March"`, tool fields null.
2. **ASSISTANT (tool request)** — `content=""` (empty on a tool-calling step), `tool_calls=[{id:"call_1",
   name:"titan_run_query", arguments:{sql:"SELECT day, count(*) …"}}]`, tokens recorded.
3. **TOOL (result)** — `role=TOOL`, `content` = **raw tool output as a string**, `tool_call_id="call_1"`
   (matches the request).
4. **ASSISTANT (final answer)** — the prose answer + `artifacts=[{type:"chart", chart_id:123, viz:"line",
   title:"DAU – March", preview_url:"/explore/?slice_id=123"}]`, plus tokens + `cost_usd`.

> Read order: human → LLM asks for a tool → tool answers → LLM's final answer + artifact.
> **The frontend shows #1 and #4 as chat bubbles; #2 and #3 become the ThoughtChain / tool timeline.**

## A6 — MCP integration (we build the *client*; the server is a separate repo)

- **Our repo** builds `mcp_client.py`: `list_tools()` (discover, cache 300s) and `call_tool(name, args)`
  (execute), forwarding the user's `Authorization: Bearer <JWT>` + workspace header. Invoked by the
  LangGraph `tools_node`; tool errors become a `ToolMessage`. **No FastMCP server is built here.**
- **Titan MCP repo** (separate) is a FastMCP server that already exists: the registered `@mcp.tool()`
  functions **are** the tool list; each re-verifies JWT + RBAC on every call; it answers `tools/list`
  (discovery) and `tools/call` (execution).
- **Two hops:** (1) our client → MCP server via MCP/JSON-RPC + Bearer JWT; (2) each MCP tool → a Titan
  REST API:

  | Tool | REST | Backend |
  |---|---|---|
  | `titan_run_query` | POST `/api/v1/query` | ClickHouse |
  | `titan_list_datasets` | GET `/api/v1/datasets` | Superset |
  | `titan_find_relevant_datasets` | GET `/api/v1/datasets/search` | Superset |
  | `titan_create_chart` | POST `/api/v1/chart` | Superset |
  | `titan_create_dashboard` | POST `/api/v1/dashboard` | Superset |

- **Nothing is hardcoded on our side** — the tool list is discovered at runtime, cached, and
  capability-filtered. Adding a tool means adding it in the MCP server, not in our client.

---

# PART B — Our extension: a multi-agent, pluggable platform

## B1 — The hook already exists: `agent_type`

`copilot_conversations.agent_type` already selects a persona (DEFAULT / SQL_EXPERT / EXPERIMENTATION).
We treat **each agent as a plugin** and extend the enum:

- `DATA_EXPLORATION` — NL → query → chart/dashboard (the base copilot's core skill).
- `MIGRATION` — **Migration Buddy** (Tableau → Superset).
- (future) `GOVERNANCE`, `SEMANTIC_MODELER`, …

A conversation's `agent_type` routes it to the right plugin. Everything else — persistence, streaming,
thought-chain, artifacts, tokens/cost, cancel, gates — is **shared**.

## B2 — Agent plugin contract

Every agent plugin declares:
- **id / display name / icon** (for the left-rail pin).
- **system prompt / persona**.
- **allowed tool capabilities** (the capability filter narrows the discovered MCP tools to this agent's).
- **its LangGraph graph** (nodes/edges) — or a shared graph parameterized per agent.
- **UI affordances**: suggested prompts, left-rail pin, any custom artifact renderers.

The chat shell is generic; agents are data + a graph. New agent = new plugin, no shell changes.

## B3 — Migration Buddy as an agent (pinned left)

- **Graph = the migration pipeline** (see `MIGRATION_BUDDY_ARCHITECTURE.md`): Ingest → Parse to IR →
  Plan/enumerate-tabs+tiles → per-tile [translate → build → **verify (numeric + structural)** → retry] →
  assemble (tabs/zones) → **fidelity report** → freeze artifacts. It runs inside the copilot runtime.
- **Tools (via MCP)** — a **Migration MCP server** (same FastMCP pattern) exposes:
  `twbx_unpack`, `twb_parse`, `calc_resolve`, `data_oracle`, `superset_create_dataset/metric/chart/
  dashboard`, `superset_query`, `diff_engine`. Runtime-discovered + capability-filtered to the MIGRATION
  agent. **On-prem**: this MCP server runs inside the customer's environment → data stays local.
- **Artifacts render inline** — the message model already has `artifacts` JSON. The migration agent emits:
  the **fidelity report** (per-tile green/yellow/red + diffs), and previews of the **created dashboards**
  — shown as chat artifacts, exactly like the DAU chart in A5.
- **Human-in-the-loop is a chat interaction** — a `RED`/ambiguous tile becomes a message: the agent asks
  "this tile is ambiguous — is it avg-rating or review-count?", the user answers, the graph resumes
  (LangGraph checkpoint/interrupt). The chat surface *is* the review UI.

## B4 — Data Exploration agent

The base copilot's core loop: NL → `titan_run_query` → `titan_create_chart`/`titan_create_dashboard` →
answer + chart artifact. This is the "daily driver" agent that keeps users in the product after the
migration is done (the *expand* to migration's *land*).

## B5 — What every agent reuses (the platform)

Conversation CRUD + persistence · SSE streaming + token events · ThoughtChain/tool timeline · `artifacts`
rendering · tokens/cost accounting · cancel + Redis gates + rate limits · MCP tool discovery + capability
filter · LangGraph checkpointer (resumable, HITL-ready). Agents differ **only** in prompt + tools + graph.

## B6 — Why this shape is strong

- **Migration is the on-ramp; exploration is the daily driver** → users land via migration and *stay* in
  one conversational surface. (Land per-project, expand into recurring exploration/governance.)
- **A platform, not a point tool** — pluggable agents compound; each new agent is cheap.
- **The artifact + thought-chain model already fits** rendering migrated dashboards + fidelity reports
  inline, and the tool-timeline naturally shows the migration agent's per-tile work.
- **On-prem via an in-customer MCP server** → the data-local differentiator, native to this design.

---

# PART C — Build order (bridge to the next steps)

1. **Chat shell (base)** — stand up (or scaffold minimally) conversations/messages, `/completions` SSE,
   the LangGraph `agent_node ⇄ tools_node` loop, Postgres + Redis. Reuse the schema in A4 verbatim.
2. **Agent plugin registry** — `agent_type` → {prompt, capabilities, graph, UI}. Wire the left-rail
   agent picker.
3. **Migration MCP server** — wrap the spike's `engine.py`/`build_ir.py`/oracle/diff as `@mcp.tool()`s;
   runtime-discovered, capability-filtered to MIGRATION. Runs in-customer-env.
4. **Migration Buddy agent graph** — port `MIGRATION_BUDDY_ARCHITECTURE.md` (verify-retry loop, tiered
   oracle, fidelity report) into the copilot runtime; render the fidelity report as a chat artifact;
   red-tile review as a HITL interrupt.
5. **Data Exploration agent** — the base NL→query→chart agent, sharing the same tools.

> This document is the **base**. `MIGRATION_BUDDY_ARCHITECTURE.md` is the migration agent's internal
> design; this file is how that agent lives inside the multi-agent copilot platform.
