"""Agent plugin registry (Part B2 contract, wired in the base shell).

`agent_type` -> {display, prompt, capabilities, ...}. The base shell ships one
active persona (DEFAULT) plus declared-but-minimal DATA_EXPLORATION and MIGRATION
plugins so the routing hook is real. Each plugin differs only in prompt +
capability filter + (later) its graph; the chat shell is generic.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..models import AgentType


@dataclass(frozen=True)
class AgentPlugin:
    agent_type: AgentType
    display_name: str
    icon: str
    system_prompt: str
    # Capability tags used to filter discovered MCP tools down to this agent's set.
    capabilities: tuple[str, ...] = field(default_factory=tuple)
    suggested_prompts: tuple[str, ...] = field(default_factory=tuple)


_DEFAULT = AgentPlugin(
    agent_type=AgentType.DEFAULT,
    display_name="Copilot",
    icon="sparkles",
    system_prompt=(
        "You are Copilot, a helpful BI assistant for Apache Superset. Answer "
        "concisely and explain what you did. "
        "Your tools come from Superset's MCP server, which uses a tool-search "
        "interface: call `search_tools` with a short query to discover the right "
        "tool (datasets, charts, dashboards, databases, schema, users, queries), "
        "then call `call_tool` with the tool's name and arguments to run it. "
        "Prefer discovering and calling a real tool over guessing."
    ),
    capabilities=("core",),
    suggested_prompts=("What can you do?", "What time is it on the server?"),
)

_DATA_EXPLORATION = AgentPlugin(
    agent_type=AgentType.DATA_EXPLORATION,
    display_name="Data Exploration",
    icon="chart",
    system_prompt=(
        "You are a data exploration agent. Turn natural-language questions into "
        "queries and charts. Prefer running a query and returning a chart artifact "
        "over guessing."
    ),
    capabilities=("query", "chart", "dataset"),
    suggested_prompts=("Show me DAU for March", "Top 10 products by revenue"),
)

_MIGRATION = AgentPlugin(
    agent_type=AgentType.MIGRATION,
    display_name="Migration Buddy",
    icon="wand",
    system_prompt=(
        "You are Migration Buddy. You migrate Tableau workbooks to Superset with "
        "verified fidelity per tile: flag, never fake. Report a per-tile fidelity "
        "summary and surface ambiguous tiles for review."
    ),
    capabilities=("migration", "query", "chart", "dataset"),
    suggested_prompts=("Migrate my Sales.twbx", "Show the fidelity report"),
)

_REGISTRY: dict[AgentType, AgentPlugin] = {
    p.agent_type: p for p in (_DEFAULT, _DATA_EXPLORATION, _MIGRATION)
}


def get_plugin(agent_type: AgentType) -> AgentPlugin:
    return _REGISTRY.get(agent_type, _DEFAULT)


def list_plugins() -> list[AgentPlugin]:
    return list(_REGISTRY.values())
