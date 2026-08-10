"""LLM factory.

Real path: ChatAnthropic (claude-opus-5 by default), streamed.
Offline path (COPILOT_FAKE_LLM=true): a minimal streaming stub so the whole
chat shell — persistence, SSE, the graph loop — runs with no API key.
"""
from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    SystemMessage,
)
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult

from ..config import get_settings


class FakeChatModel(BaseChatModel):
    """Echoes the latest human turn back token-by-token. No tool calls."""

    @property
    def _llm_type(self) -> str:
        return "fake-echo"

    def bind_tools(self, tools: Any, **kwargs: Any):  # noqa: ANN401
        # The stub does not call tools; binding is a no-op so the graph is happy.
        return self

    def _last_human(self, messages: list[BaseMessage]) -> str:
        for m in reversed(messages):
            if isinstance(m, HumanMessage):
                return m.content if isinstance(m.content, str) else str(m.content)
        return ""

    def _reply(self, messages: list[BaseMessage]) -> str:
        return f"(offline stub) You said: {self._last_human(messages)}"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        text = self._reply(messages)
        msg = AIMessage(
            content=text,
            usage_metadata={
                "input_tokens": sum(len(str(m.content)) for m in messages) // 4,
                "output_tokens": len(text) // 4,
                "total_tokens": 0,
            },
        )
        return ChatResult(generations=[ChatGeneration(message=msg)])

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        for word in self._reply(messages).split(" "):
            chunk = ChatGenerationChunk(message=AIMessageChunk(content=word + " "))
            if run_manager:
                run_manager.on_llm_new_token(word + " ", chunk=chunk)
            yield chunk


def build_llm(*, enable_tools: bool = True) -> BaseChatModel:
    """enable_tools=False builds a plain, MCP-free model — for trivial,
    tool-free calls (title generation) that shouldn't spawn a subprocess
    wired up to Superset's full toolset just to summarize a sentence."""
    s = get_settings()
    if s.copilot_use_claude_sdk:
        # Local testing: inference via the Claude Agent SDK (subscription auth).
        import os

        if s.claude_code_oauth_token:
            # Export so the SDK-spawned `claude` CLI authenticates with it.
            os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = s.claude_code_oauth_token
        from .claude_sdk_llm import ClaudeSDKChatModel

        return ClaudeSDKChatModel(enable_tools=enable_tools)
    if s.copilot_fake_llm or not s.anthropic_api_key:
        return FakeChatModel()

    import os

    from langchain_anthropic import ChatAnthropic

    kwargs: dict[str, Any] = {
        "model": s.copilot_model,
        "max_tokens": s.copilot_max_tokens,
        "api_key": s.anthropic_api_key,
        "streaming": True,
    }
    # Anthropic-compatible endpoint (z.ai/GLM etc.) via COPILOT_ANTHROPIC_BASE_URL
    # or the ambient ANTHROPIC_BASE_URL.
    base_url = s.copilot_anthropic_base_url or os.environ.get("ANTHROPIC_BASE_URL", "")
    if base_url and base_url != "https://api.anthropic.com":
        kwargs["base_url"] = base_url
    if s.copilot_thinking:
        # Adaptive thinking on Claude 4.6+; needs a recent langchain-anthropic.
        kwargs["thinking"] = {"type": "adaptive"}
    return ChatAnthropic(**kwargs)


TITLE_SYSTEM_PROMPT = (
    "Generate a short, specific title (3-6 words) for this conversation, "
    "written like a document title, not a sentence or a greeting. No "
    "quotes, no trailing punctuation, no preamble — reply with the title "
    "and nothing else."
)

# A fixed, neutral default — never the user's own raw message. Used as the
# immediate placeholder before the first reply lands, and as the fallback
# when title generation fails or is disabled (COPILOT_FAKE_LLM).
DEFAULT_TITLE = "General Conversation"


async def generate_title(user_message: str, assistant_reply: str) -> str:
    """A cheap, tool-free LLM call producing a short title for a
    conversation's first exchange — same idea as Claude/ChatGPT auto-titling
    a new chat. Always returns *something*: falls back to DEFAULT_TITLE
    rather than let a titling hiccup break message persistence.
    """
    s = get_settings()
    if s.copilot_fake_llm:
        return DEFAULT_TITLE
    try:
        llm = build_llm(enable_tools=False)
        response = await llm.ainvoke(
            [
                SystemMessage(content=TITLE_SYSTEM_PROMPT),
                HumanMessage(
                    content=f"User: {user_message}\n\nAssistant: {assistant_reply}"
                ),
            ]
        )
        title = str(response.content).strip().strip("\"'").strip()
        # Guard against a verbose/misbehaving model — a title is one short
        # line, not a paragraph or an explanation.
        if title and len(title) <= 80 and "\n" not in title:
            return title
    except Exception:  # noqa: BLE001 — titling must never break a real turn
        pass
    return DEFAULT_TITLE
