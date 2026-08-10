"""LangChain chat-model adapter over the Claude Agent SDK (`query()`).

For LOCAL TESTING ONLY: the Agent SDK spawns the local `claude` CLI, which uses
the machine's Claude Code subscription auth automatically. This lets the LangGraph
agent run real Claude inference without an API key. Requires the CLI to be logged
in (`claude setup-token`).

Tool-calling runs through the SDK's own harness, not LangGraph's tools_node
(bind_tools() is a no-op here) — so this configures the SDK session directly
with Superset's MCP server (matching COPILOT_MCP_ENABLED/COPILOT_MCP_URL) and
scopes it to exactly that server's tools. Without setting_sources=[] and
strict_mcp_config=True, the spawned `claude` process would fall back to
whatever MCP servers and settings happen to be configured on this machine
(e.g. this developer's own unrelated tools), instead of Superset's.
"""
from __future__ import annotations

import asyncio
import tempfile
from collections.abc import AsyncIterator, Iterator
from typing import Any

from langchain_core.callbacks import (
    AsyncCallbackManagerForLLMRun,
    CallbackManagerForLLMRun,
)
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    SystemMessage,
)
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult


def _render(messages: list[BaseMessage]) -> tuple[str, str]:
    """Flatten the LangChain conversation into (system_prompt, prompt)."""
    system = ""
    lines: list[str] = []
    for m in messages:
        content = m.content if isinstance(m.content, str) else str(m.content)
        if isinstance(m, SystemMessage):
            system = content
        elif isinstance(m, HumanMessage):
            lines.append(f"User: {content}")
        elif isinstance(m, AIMessage) and content:
            lines.append(f"Assistant: {content}")
    return system, "\n".join(lines)


class ClaudeSDKChatModel(BaseChatModel):
    """Runs a turn through `claude_agent_sdk.query()` and returns the text."""

    @property
    def _llm_type(self) -> str:
        return "claude-agent-sdk"

    def bind_tools(self, tools: Any, **kwargs: Any):  # noqa: ANN401
        # The LangGraph-bound `tools` (from mcp_tools.load_tools()) aren't used
        # here — the Agent SDK gets Superset's MCP server wired directly in
        # _options() instead. No-op so the graph stays happy either way.
        return self

    @staticmethod
    def _options(system: str):
        from claude_agent_sdk import ClaudeAgentOptions

        from ..config import get_settings

        s = get_settings()
        mcp_servers: dict[str, Any] = {}
        allowed_tools: list[str] = []
        if s.copilot_mcp_enabled:
            mcp_servers["superset"] = {"type": "http", "url": s.copilot_mcp_url}
            # Superset's MCP exposes a tool-search interface, not one tool per
            # resource (see mcp_tools.py): search_tools finds the right tool,
            # call_tool invokes it. Allow exactly that server's tools, named
            # per the SDK's mcp__<server>__<tool> convention.
            allowed_tools = [
                "mcp__superset__search_tools",
                "mcp__superset__call_tool",
                "mcp__superset__health_check",
                "mcp__superset__get_instance_info",
            ]

        return ClaudeAgentOptions(
            allowed_tools=allowed_tools,
            mcp_servers=mcp_servers,
            # Use only what's configured above — not this machine's ambient
            # ~/.claude user/project/local settings (which is what leaked
            # unrelated tools in) or any MCP servers registered outside of
            # mcp_servers.
            setting_sources=[],
            strict_mcp_config=True,
            cwd=tempfile.gettempdir(),
            system_prompt=system or "You are a helpful assistant.",
        )

    async def _run(self, messages: list[BaseMessage]) -> str:
        from claude_agent_sdk import AssistantMessage, TextBlock, query

        system, prompt = _render(messages)
        text = ""
        async for msg in query(prompt=prompt or " ", options=self._options(system)):
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        text += block.text
        return text

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        text = await self._run(messages)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=text))])

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        text = asyncio.run(self._run(messages))
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=text))])

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        from claude_agent_sdk import AssistantMessage, TextBlock, query

        system, prompt = _render(messages)
        async for msg in query(prompt=prompt or " ", options=self._options(system)):
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        chunk = ChatGenerationChunk(
                            message=AIMessageChunk(content=block.text)
                        )
                        if run_manager:
                            await run_manager.on_llm_new_token(block.text, chunk=chunk)
                        yield chunk

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        raise NotImplementedError("Use the async path (the graph runs async).")
