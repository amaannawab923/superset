"""MCP tool discovery (A6) — the real tool layer.

Connects to the local Superset MCP server (`superset mcp run`, streamable-http)
and loads its tools as LangChain tools for the LangGraph tools_node. Falls back
to the local stub tool when MCP is disabled or the server is unreachable, so the
shell keeps working offline.
"""
from __future__ import annotations

import logging

from langchain_core.tools import BaseTool

from ..config import get_settings
from .tools import LOCAL_TOOLS

log = logging.getLogger(__name__)


async def load_tools() -> list[BaseTool]:
    s = get_settings()
    if not s.copilot_mcp_enabled:
        return LOCAL_TOOLS
    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient

        client = MultiServerMCPClient(
            {
                "superset": {
                    "url": s.copilot_mcp_url,
                    "transport": "streamable_http",
                }
            }
        )
        tools = await client.get_tools()
        if not tools:
            log.warning("Superset MCP returned no tools; using local stub tool.")
            return LOCAL_TOOLS
        log.info(
            "Loaded %d tools from Superset MCP at %s: %s",
            len(tools),
            s.copilot_mcp_url,
            ", ".join(t.name for t in tools[:12]),
        )
        return tools
    except Exception as exc:  # noqa: BLE001 — degrade gracefully, never crash the loop
        log.warning(
            "Superset MCP unavailable at %s (%s); using local stub tool.",
            s.copilot_mcp_url,
            exc,
        )
        return LOCAL_TOOLS
