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
import json
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


def _tool_result_text(content: Any) -> str:
    """Flatten a ToolResultBlock's content (str, or a list of content blocks
    with a "text" field) into one string worth attempting to JSON-parse."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            b.get("text", "") if isinstance(b, dict) else getattr(b, "text", "")
            for b in content
        )
    return ""


_UNTRUSTED_OPEN = "<UNTRUSTED-CONTENT>"
_UNTRUSTED_CLOSE = "</UNTRUSTED-CONTENT>"


def _strip_untrusted_wrapper(value: str) -> str:
    """Superset's MCP wraps free-text string fields (e.g. a chart's name) in
    <UNTRUSTED-CONTENT> delimiters as a prompt-injection defense (see
    superset/mcp_service/utils/sanitization.py) — strip them for display; the
    wrapping is meant to stop the *model* from treating the value as
    instructions, not to be shown verbatim in a UI card."""
    text = value.strip()
    if text.startswith(_UNTRUSTED_OPEN) and text.endswith(_UNTRUSTED_CLOSE):
        text = text[len(_UNTRUSTED_OPEN) : -len(_UNTRUSTED_CLOSE)]
    return text.strip()


def _chart_artifact_from_dict(data: dict) -> dict | None:
    """Recognize a chart-shaped MCP tool result (generate_chart/update_chart/
    get_chart_info all return a ChartInfo-shaped object) and normalize it into
    the artifact card's {type, id, name, url} shape. None if it doesn't look
    like one — this is deliberately a duck-typed heuristic, not tied to one
    tool name, since call_tool can invoke any of several chart tools."""
    chart = data.get("chart") if isinstance(data.get("chart"), dict) else data
    if not isinstance(chart, dict):
        return None
    chart_id = chart.get("id")
    name = chart.get("slice_name") or chart.get("name")
    if chart_id is None or not name:
        return None
    name = _strip_untrusted_wrapper(str(name))
    url = data.get("explore_url") or chart.get("url")
    return {"type": "chart", "id": chart_id, "name": name, "url": url}


def _extract_chart_artifacts(user_message: Any) -> list[dict]:
    """Scan a Claude Agent SDK UserMessage (the turn carrying ToolResultBlocks
    for whatever the assistant just called) for chart-creation results."""
    from claude_agent_sdk import ToolResultBlock

    artifacts: list[dict] = []
    for block in getattr(user_message, "content", None) or []:
        if not isinstance(block, ToolResultBlock) or block.is_error:
            continue
        text = _tool_result_text(block.content)
        try:
            data = json.loads(text)
        except (ValueError, TypeError):
            continue
        if isinstance(data, dict) and (artifact := _chart_artifact_from_dict(data)):
            artifacts.append(artifact)
    return artifacts


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

    async def _run(self, messages: list[BaseMessage]) -> tuple[str, list[dict]]:
        from claude_agent_sdk import AssistantMessage, TextBlock, UserMessage, query

        system, prompt = _render(messages)
        text = ""
        artifacts: list[dict] = []
        async for msg in query(prompt=prompt or " ", options=self._options(system)):
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        text += block.text
            elif isinstance(msg, UserMessage):
                artifacts.extend(_extract_chart_artifacts(msg))
        return text, artifacts

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        text, artifacts = await self._run(messages)
        additional_kwargs = {"artifacts": artifacts} if artifacts else {}
        return ChatResult(
            generations=[
                ChatGeneration(
                    message=AIMessage(content=text, additional_kwargs=additional_kwargs)
                )
            ]
        )

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        text, artifacts = asyncio.run(self._run(messages))
        additional_kwargs = {"artifacts": artifacts} if artifacts else {}
        return ChatResult(
            generations=[
                ChatGeneration(
                    message=AIMessage(content=text, additional_kwargs=additional_kwargs)
                )
            ]
        )

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        from claude_agent_sdk import AssistantMessage, TextBlock, UserMessage, query

        system, prompt = _render(messages)
        artifacts: list[dict] = []
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
            elif isinstance(msg, UserMessage):
                artifacts.extend(_extract_chart_artifacts(msg))
        if artifacts:
            # A trailing, content-less chunk: LangChain merges AIMessageChunks
            # by concatenating content and updating additional_kwargs, so this
            # attaches the artifacts to the aggregated final message without
            # appending any visible text.
            yield ChatGenerationChunk(
                message=AIMessageChunk(
                    content="", additional_kwargs={"artifacts": artifacts}
                )
            )

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        raise NotImplementedError("Use the async path (the graph runs async).")
