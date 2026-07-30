"""Verify the agent_node <-> tools_node loop + full A5 four-row turn, offline.

Patches the LLM with a stub that calls a tool once, then answers — exercising
the branch the echo stub can't reach.
"""
from __future__ import annotations

import asyncio
import os
from typing import Any

os.environ.setdefault("COPILOT_DATABASE_URL", "sqlite+aiosqlite:///./tool_smoke.db")
os.environ.setdefault("COPILOT_MCP_ENABLED", "false")  # exercise the stub tool

from langchain_core.language_models.chat_models import BaseChatModel  # noqa: E402
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage  # noqa: E402
from langchain_core.outputs import ChatGeneration, ChatResult  # noqa: E402


class ToolCallingFake(BaseChatModel):
    @property
    def _llm_type(self) -> str:
        return "fake-tool"

    def bind_tools(self, tools: Any, **kwargs: Any):  # noqa: ANN401
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        has_tool_result = any(isinstance(m, ToolMessage) for m in messages)
        if has_tool_result:
            tool_out = next(m for m in reversed(messages) if isinstance(m, ToolMessage))
            msg = AIMessage(
                content=f"The server time is {tool_out.content}.",
                usage_metadata={"input_tokens": 10, "output_tokens": 8, "total_tokens": 18},
            )
        else:
            msg = AIMessage(
                content="",
                tool_calls=[
                    {"name": "get_server_time", "args": {"timezone_name": "UTC"}, "id": "call_1"}
                ],
                usage_metadata={"input_tokens": 12, "output_tokens": 4, "total_tokens": 16},
            )
        return ChatResult(generations=[ChatGeneration(message=msg)])


async def main() -> None:
    if os.path.exists("tool_smoke.db"):
        os.remove("tool_smoke.db")

    import app.agent.graph as graph_mod

    graph_mod.build_llm = lambda: ToolCallingFake()  # patch factory
    graph_mod._graph_cache.clear()

    from app.db import init_db
    from app.models import AgentType, Conversation
    from app.db import SessionLocal
    from app.completion import GenerateCompletionCommand

    await init_db()
    async with SessionLocal() as s:
        conv = Conversation(user_id=1, workspace_id="default", agent_type=AgentType.DEFAULT)
        s.add(conv)
        await s.commit()
        await s.refresh(conv)
        conv_id = conv.id

        cmd = GenerateCompletionCommand(
            conv=conv, user_id=1, user_message="what time is it?", suggested_id=None
        )

    kinds = []
    async for chunk in cmd.stream():
        for line in chunk.splitlines():
            if line.startswith("event: "):
                kinds.append(line[7:])
                print(" ", line[7:])

    print("\nevent kinds:", kinds)
    assert "tool_call" in kinds, "agent_node did not emit a tool call"
    assert "tool_result" in kinds, "tools_node did not run"
    assert "final" in kinds

    from sqlalchemy import select
    from app.models import Message

    async with SessionLocal() as s:
        rows = (
            await s.scalars(
                select(Message).where(Message.conversation_id == conv_id).order_by(Message.created_at)
            )
        ).all()
    print("\nA5 turn rows:")
    for m in rows:
        extra = f" tool_calls={m.tool_calls}" if m.tool_calls else ""
        extra += f" tool_call_id={m.tool_call_id}" if m.tool_call_id else ""
        print(f"  {m.role.value:>9}  {m.content[:50]!r}{extra}")

    roles = [m.role.value for m in rows]
    assert roles == ["USER", "ASSISTANT", "TOOL", "ASSISTANT"], roles
    assert rows[1].tool_calls, "assistant tool-request row missing tool_calls"
    assert rows[2].tool_call_id == "call_1"
    print("\nTOOL-LOOP SMOKE OK")


if __name__ == "__main__":
    asyncio.run(main())
