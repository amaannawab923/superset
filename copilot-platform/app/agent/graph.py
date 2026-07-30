"""The LangGraph agent loop: agent_node <-> tools_node (A1 / Part C step 1).

    agent_node --should_continue--> tools_node --> agent_node --> ... --> END

Repeat until the LLM emits no more tool_calls. Tools come from the Superset MCP
server (A6) via mcp_tools.load_tools(), with a local-stub fallback. A checkpointer
makes runs resumable (and HITL-ready). The base shell uses an in-memory
checkpointer; prod swaps in a Postgres one.
"""
from __future__ import annotations

import asyncio

from langchain_core.messages import SystemMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.graph.message import MessagesState
from langgraph.prebuilt import ToolNode

from ..models import AgentType
from .llm import build_llm
from .mcp_tools import load_tools
from .registry import AgentPlugin, get_plugin

RECURSION_LIMIT = 25  # loop guard (per A1 "loop guards")

_graph_cache: dict[AgentType, object] = {}
_lock = asyncio.Lock()


async def _build_graph(plugin: AgentPlugin):
    # A6: discover tools at runtime from the Superset MCP server. Capability
    # filtering by plugin.capabilities is a future refinement; the DEFAULT agent
    # gets the full discovered set.
    tools = await load_tools()
    llm = build_llm().bind_tools(tools)
    system = SystemMessage(content=plugin.system_prompt)

    async def agent_node(state: MessagesState) -> dict:
        response = await llm.ainvoke([system, *state["messages"]])
        return {"messages": [response]}

    def should_continue(state: MessagesState) -> str:
        last = state["messages"][-1]
        if getattr(last, "tool_calls", None):
            return "tools"
        return END

    builder = StateGraph(MessagesState)
    builder.add_node("agent", agent_node)
    builder.add_node("tools", ToolNode(tools))
    builder.set_entry_point("agent")
    builder.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
    builder.add_edge("tools", "agent")

    return builder.compile(checkpointer=MemorySaver())


async def get_graph_for(agent_type: AgentType):
    """One compiled graph per agent_type (cached). Async because tool discovery
    (MCP) is async."""
    async with _lock:
        if agent_type not in _graph_cache:
            _graph_cache[agent_type] = await _build_graph(get_plugin(agent_type))
        return _graph_cache[agent_type]
