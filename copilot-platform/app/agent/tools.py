"""Tool layer.

In the full platform (Part C step 3) the tool list is *discovered at runtime*
from an MCP server (`tools/list`, cached 300s) and capability-filtered per agent
(A6). For the base shell we register one deterministic local tool so the
agent_node <-> tools_node loop is exercised end to end. Swap `LOCAL_TOOLS` for
the MCP-discovered set without touching the graph.
"""
from __future__ import annotations

from datetime import datetime, timezone

from langchain_core.tools import tool


@tool
def get_server_time(timezone_name: str = "UTC") -> str:
    """Return the current server time. A stand-in for a real MCP tool so the
    agent loop can be exercised offline. `timezone_name` is informational."""
    return f"{datetime.now(timezone.utc).isoformat()} ({timezone_name})"


LOCAL_TOOLS = [get_server_time]
