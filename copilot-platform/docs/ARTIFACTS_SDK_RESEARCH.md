# Superset Artifact SDK — Preset Copilot Integration

*Standalone product brief. Evidence-based, independent of any other project. The question:
is a "Superset SDK for Artifacts" that integrates with **Preset's copilot** a real opportunity,
what pain does it resolve, and how do we frame it?*

---

## Verdict

**Medium — a real, competitively-validated gap, but with a genuine "is a separate SDK the right
vehicle?" risk.** The rating forks on where it lives:

- **As an OSS layer on Superset's Slice model + MCP tools + Extension System → 7/10.** Defensible,
  not dependent on Preset exposing proprietary APIs, and built where the durable object model
  already lives and where Superset core is actively investing.
- **As a Preset-proprietary wrapper around the Chatbot + Embedded SDK → 5/10.** The gap is real,
  but Preset owns both ends of the seam and can simply ship "promote to Slice" as an internal
  feature — a third-party/separate SDK there is fighting the platform owner.

---

## What Preset's copilot actually is today (the integration target)

Preset ships **two AI surfaces + an MCP server**, not one unified copilot:

| Surface | What it does | Status | Output |
|---|---|---|---|
| **AI Assist** | text-to-SQL inside SQL Lab (find tables/joins, emit a query) | **GA**, but narrow (BigQuery/Postgres/Snowflake, one schema/session) | **SQL text** — you still turn it into a dataset → chart → dashboard by hand |
| **Chatbot** | NL → **a visualization**, ranked tables, insights; iterate to a "full dashboard" in chat; semantic-layer-grounded + permission-aware (RLS/RBAC) | **Enterprise-only, recently launched, docs marketing-thin** | Charts/insights **inline in chat** — persistence/reuse mechanics **not documented** |
| **Preset MCP** | exposes the governed platform to Claude/Cursor/any MCP client | shipping | tool calls |

Preset's stated strategy is explicitly **"copilot, not autopilot"** — human-in-the-loop, "validate in
the actual BI UI." Their strategy writing does **not** emphasize auto-insights or saved/reusable
AI-generated objects.

---

## The concrete gap (the whitespace)

**Preset has an unwired seam:** a mature **Embedded SDK** (guest tokens, RLS, ~$500/mo add-on) on one
side, serving only **pre-built** dashboards — and a new **Chatbot** on the other, whose output appears
**chat-ephemeral** with no documented path to persist, embed, or share it. The two live in the same
pricing tiers but **are not wired together.**

Concretely, with a copilot-generated viz today you likely **cannot** (or must do manually, multi-step):

- **Promote** the chatbot's chart into a real, saved Superset **Slice** with a stable ID.
- **Embed** it via the Embedded SDK + guest token (embedding targets saved dashboards, not chat output).
- **Share** it as a first-class governed object (URL + permissions + RLS), not a chat transcript.
- **Reuse / parameterize** it as a component in other dashboards or host apps.
- Get a **typed, serializable representation** (chart spec + query + dataset/semantic binding + governance
  context) that a host application can package and re-render.

**This seam is competitively validated as a must-have — and Preset is the laggard:**

- **ThoughtSpot Spotter** — NL answers **pin to governed Liveboards** (saved, shareable).
- **Hex Magic** — generated SQL/charts are **notebook cells** in a saveable/embeddable app.
- **Tableau Pulse** — produces **persistent metric objects** with scheduled digests.
- **Power BI Copilot** — generates visuals **inside a saved report**.

Everyone else turns copilot output into a durable object. Preset's copilot output looks ephemeral while
its (excellent) embedding layer only serves pre-built dashboards. **That disconnect is the product.**

---

## What the Artifact SDK is

A missing **"promote & package" layer** that turns ephemeral copilot output into a durable, governed,
embeddable Superset artifact. Two parts:

1. **The artifact contract** — a typed, serializable object:
   `{ query (query_context) + chart spec (form_data) + dataset / semantic binding + governance context
   (RLS / permissions) }`. Addressable, versionable, re-renderable.
2. **The lifecycle** — **promote** (chat viz → saved Slice with stable ID) → **embed** (Embedded SDK +
   guest token) → **share** (governed URL) → **reuse** (drop into other dashboards / host apps).

**Integration point with the copilot:** the copilot *emits an artifact object* rather than only painting
an ephemeral inline chart; the SDK is what the copilot — and any host app — calls to render, persist,
embed, and share it. On the Preset side this is literally the wire between **Chatbot** and **Embedded**
that doesn't exist today.

The technical raw material already exists in Superset: a chart *is* a `form_data` + `query_context` JSON
spec, and `@superset-ui/core`'s `SuperChart` / `ChartProps` renders one standalone from
`{ formData, queriesData, datasource }` — no app shell required. The SDK is the packaging + save/embed
lifecycle around that, not a new renderer.

---

## Where it lives — OSS vs Preset-proprietary

- **OSS Superset has no native copilot UI** (the native text-to-SQL SIP-166 was **denied**). But OSS
  core now carries the **MCP plumbing** (PR #36151 — *extensions can register custom AI tools*), the
  **Slice / dashboard object model**, and the **Extension System**. That's the durable-object substrate.
- **Proprietary to Preset:** the Chatbot, AI Assist, the semantic layer, and the Embedded SDK's hosted
  guest-token service.
- **The cleaner bet is OSS-first** — build the artifact contract + promote/embed lifecycle on the Slice
  model + MCP tools + Extension System. It's contribution-friendly, reaches all of Superset, doesn't
  depend on Preset exposing Chatbot internals — **and Preset (who is investing in exactly this core
  plumbing) is the natural adopter** to wire it into their copilot. That satisfies "on the Preset side,
  integrating with the copilot" *without* a proprietary-API dependency.

---

## How to frame it for end users

The one-liner: **"Turn what the copilot made into something you can keep."** A copilot answer stops
being a disposable chat bubble and becomes a governed, saved, embeddable chart — with one action.

- To **the analyst:** "Your AI-generated chart, saved as a real Superset chart you can pin, share, and
  reuse — not lost when the chat closes."
- To **the app developer:** "Embed a copilot-generated, governed chart into your product with the SDK you
  already use for dashboards — RLS and permissions carried through."
- To **the platform (Preset):** "The wire between your Chatbot and your Embedded SDK — the durable
  artifact layer your competitors already ship and you don't."

---

## Honest risks

- **Preset can close the seam themselves.** "Promote chat chart → Slice" is a feature they could ship
  internally; a *separate* SDK there competes with the platform owner. This is the biggest risk.
- **Strategy tension.** Preset's public stance is "copilot-not-autopilot, validate in the governed UI."
  An SDK that packages/exports copilot output runs mildly against their "keep it in our UI" instinct.
- **Small TAM today.** The Chatbot (the only surface that emits a viz) is Enterprise-only and early;
  AI Assist emits SQL text, not a viz.
- **OSS community is cautious about native AI** (SIP-166 denied) — an upstream contribution needs a SIP
  and PMC buy-in, and Preset may absorb the best ideas into the commercial product.
- **Mitigation:** anchor on the **OSS artifact-contract + MCP/extension** substrate (useful regardless of
  who ships the copilot UI), so the work has value even if Preset builds their own promote button — it
  becomes the standard object the ecosystem's AI tools emit and any embed target consumes.

---

## Recommendation

The **problem** is real and competitively proven: copilot output → durable, embeddable, governed
Superset artifact is a genuine missing link, and Preset visibly has the unwired seam. The **risk** is
positioning: build it as an **OSS artifact contract + promote/embed lifecycle on the Slice model + MCP
tools + Extension System**, not as a bet on proprietary Chatbot APIs. That way it stands alone, it's the
natural thing Preset (and community AI extensions) wire their copilot into, and it survives Preset
shipping their own version.

## Sources

- Preset Chatbot: https://preset.io/ai/chatbot/
- Preset AI Assist (docs): https://docs.preset.io/docs/ai-assisted-sql-querying
- AI Assist build blog: https://preset.io/blog/building-preset-ai-assist-how-we-brought-text-to-sql-into-apache-superset/
- Preset strategy (copilot-not-autopilot): https://preset.io/blog/ai-in-bi-the-path-to-full-self-driving-analytics/
- MCP in OSS core (Nov 2025 update): https://preset.io/blog/apache-superset-community-update-november-2025/
- SIP-166 native text-to-SQL (denied): https://github.com/apache/superset/issues/33215
- Preset Embedded SDK: https://www.npmjs.com/package/@superset-ui/embedded-sdk · https://docs.preset.io/docs/step-2-deployment
- Community AI extension (Vambery): https://github.com/apache/superset/discussions/38356
