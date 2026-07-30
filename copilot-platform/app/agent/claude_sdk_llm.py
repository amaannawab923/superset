"""LangChain chat-model adapter over the Claude Agent SDK (`query()`).

For LOCAL TESTING ONLY: the Agent SDK spawns the local `claude` CLI, which uses
the machine's Claude Code subscription auth automatically. This lets the LangGraph
agent run real Claude inference without an API key. Requires the CLI to be logged
in (`claude setup-token`). Tool-calling is not wired through this path — the SDK
runs its own harness — so use it with COPILOT_MCP_ENABLED=false (the agent just
produces a text answer).
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
        # The Agent SDK owns its own tool harness; we don't surface LangGraph
        # tool-calling through this path. No-op so the graph stays happy.
        return self

    @staticmethod
    def _options(system: str):
        from claude_agent_sdk import ClaudeAgentOptions

        return ClaudeAgentOptions(
            allowed_tools=[],  # pure chat completion
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
