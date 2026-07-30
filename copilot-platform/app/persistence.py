"""Conversation/message persistence — loads history into LangChain messages and
writes back the A5 four-row turn model (USER / ASSISTANT tool-request / TOOL /
ASSISTANT final), all sharing one run_id.
"""
from __future__ import annotations

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import (
    Conversation,
    Message,
    MessageRole,
    MessageStatus,
    TitleSource,
    _now,
)


async def get_owned_conversation(
    session: AsyncSession, conv_id: str, user_id: int
) -> Conversation | None:
    row = await session.get(Conversation, conv_id)
    if row is None or row.user_id != user_id:
        return None
    return row


async def load_history(session: AsyncSession, conv_id: str) -> list[BaseMessage]:
    """Active messages oldest-first, as LangChain messages (A3 resume)."""
    result = await session.scalars(
        select(Message)
        .where(
            Message.conversation_id == conv_id,
            Message.status == MessageStatus.ACTIVE,
        )
        .order_by(Message.created_at, Message.id)
    )
    out: list[BaseMessage] = []
    for m in result:
        if m.role == MessageRole.USER:
            out.append(HumanMessage(content=m.content))
        elif m.role == MessageRole.SYSTEM:
            out.append(SystemMessage(content=m.content))
        elif m.role == MessageRole.TOOL:
            out.append(
                ToolMessage(content=m.content, tool_call_id=m.tool_call_id or "")
            )
        elif m.role == MessageRole.ASSISTANT:
            out.append(
                AIMessage(content=m.content, tool_calls=m.tool_calls or [])
            )
    return out


async def add_message(
    session: AsyncSession,
    *,
    conv: Conversation,
    run_id: str,
    role: MessageRole,
    content: str = "",
    tool_calls: list | None = None,
    tool_call_id: str | None = None,
    artifacts: list | None = None,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    metadata: dict | None = None,
    suggested_id: str | None = None,
) -> Message:
    msg = Message(
        conversation_id=conv.id,
        workspace_id=conv.workspace_id,
        role=role,
        content=content,
        tool_calls=tool_calls,
        tool_call_id=tool_call_id,
        run_id=run_id,
        artifacts=artifacts,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        metadata_json=metadata or {},
        suggested_id=suggested_id,
    )
    session.add(msg)
    return msg


async def touch_conversation(session: AsyncSession, conv: Conversation) -> None:
    """Refresh denormalized sidebar fields (last_message_at, message_count)."""
    from sqlalchemy import func

    n = await session.scalar(
        select(func.count(Message.id)).where(
            Message.conversation_id == conv.id,
            Message.status == MessageStatus.ACTIVE,
        )
    )
    conv.message_count = int(n or 0)
    conv.last_message_at = _now()


def set_system_title(conv: Conversation, title: str) -> None:
    """LLM-written 3-5 word title, only if the user hasn't renamed (A3)."""
    if conv.title_source == TitleSource.USER:
        return
    conv.title = title[:255]
    conv.title_source = TitleSource.SYSTEM
