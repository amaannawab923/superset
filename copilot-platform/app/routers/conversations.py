"""Conversation + message CRUD (A2 routes)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..agent.registry import list_plugins
from ..db import get_session
from ..deps import Principal, current_principal, require_feature
from ..models import (
    Conversation,
    ConversationStatus,
    Message,
    MessageStatus,
    TitleSource,
)
from ..persistence import get_owned_conversation
from ..schemas import (
    ConversationOut,
    CreateConversation,
    MessageOut,
    MoveConversation,
    PatchConversation,
)

router = APIRouter(
    prefix="/api/v1/copilot",
    tags=["copilot"],
    dependencies=[Depends(require_feature)],
)


@router.get("/agents")
async def list_agents() -> list[dict]:
    """Left-rail agent picker (Part B2 plugin contract)."""
    return [
        {
            "agent_type": p.agent_type.value,
            "display_name": p.display_name,
            "icon": p.icon,
            "suggested_prompts": list(p.suggested_prompts),
        }
        for p in list_plugins()
    ]


@router.post("/conversations", response_model=ConversationOut, status_code=201)
async def create_conversation(
    body: CreateConversation,
    principal: Principal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
) -> Conversation:
    conv = Conversation(
        user_id=principal.user_id,
        workspace_id=principal.workspace_id,
        agent_type=body.agent_type,
        title=body.title,
        title_source=TitleSource.USER if body.title else TitleSource.SYSTEM,
    )
    session.add(conv)
    await session.commit()
    await session.refresh(conv)
    return conv


@router.get("/conversations", response_model=list[ConversationOut])
async def list_conversations(
    principal: Principal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
    limit: int = Query(50, le=200),
    offset: int = 0,
) -> list[Conversation]:
    rows = await session.scalars(
        select(Conversation)
        .where(
            Conversation.user_id == principal.user_id,
            Conversation.workspace_id == principal.workspace_id,
            Conversation.status != ConversationStatus.DELETED,
        )
        .order_by(
            Conversation.pinned.desc(),
            Conversation.sort_order.asc(),
            Conversation.last_message_at.desc().nullslast(),
            Conversation.created_at.desc(),
        )
        .limit(limit)
        .offset(offset)
    )
    return list(rows)


@router.get("/conversations/{conv_id}", response_model=ConversationOut)
async def get_conversation(
    conv_id: str,
    principal: Principal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
) -> Conversation:
    conv = await get_owned_conversation(session, conv_id, principal.user_id)
    if conv is None or conv.status == ConversationStatus.DELETED:
        raise HTTPException(404, "conversation not found")
    return conv


@router.patch("/conversations/{conv_id}", response_model=ConversationOut)
async def patch_conversation(
    conv_id: str,
    body: PatchConversation,
    principal: Principal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
) -> Conversation:
    conv = await get_owned_conversation(session, conv_id, principal.user_id)
    if conv is None:
        raise HTTPException(404, "conversation not found")
    if body.title is not None:
        conv.title = body.title
        conv.title_source = TitleSource.USER  # stop auto-overwrite (A4)
    if body.status is not None:
        conv.status = body.status
    if body.pinned is not None:
        conv.metadata_json = {**conv.metadata_json, "pinned": body.pinned}
    await session.commit()
    await session.refresh(conv)
    return conv


@router.post("/conversations/{conv_id}/move", response_model=ConversationOut)
async def move_conversation(
    conv_id: str,
    body: MoveConversation,
    principal: Principal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
) -> Conversation:
    conv = await get_owned_conversation(session, conv_id, principal.user_id)
    if conv is None or conv.status == ConversationStatus.DELETED:
        raise HTTPException(404, "conversation not found")

    # The section a move happens within mirrors the sidebar's own bucketing:
    # same pin state, same group.
    group_filter = (
        Conversation.group_id.is_(None)
        if conv.group_id is None
        else Conversation.group_id == conv.group_id
    )
    section = list(
        await session.scalars(
            select(Conversation)
            .where(
                Conversation.user_id == principal.user_id,
                Conversation.workspace_id == principal.workspace_id,
                Conversation.status != ConversationStatus.DELETED,
                Conversation.pinned == conv.pinned,
                group_filter,
            )
            .order_by(
                Conversation.sort_order.asc(),
                Conversation.last_message_at.desc().nullslast(),
                Conversation.created_at.desc(),
            )
        )
    )
    idx = next(i for i, c in enumerate(section) if c.id == conv_id)
    target = idx - 1 if body.direction == "up" else idx + 1
    if target < 0 or target >= len(section):
        return conv  # already at the edge — no-op, not an error

    section[idx], section[target] = section[target], section[idx]
    # Resequence the whole section rather than compute a fractional-index
    # midpoint: sections are small (tens of conversations per user), so an
    # O(n) rewrite is simpler and sidesteps float-tie edge cases while most
    # rows still share the default sort_order of 0.0.
    for i, c in enumerate(section):
        c.sort_order = float(i)
    await session.commit()
    await session.refresh(conv)
    return conv


@router.delete("/conversations/{conv_id}", status_code=204)
async def delete_conversation(
    conv_id: str,
    principal: Principal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
) -> None:
    conv = await get_owned_conversation(session, conv_id, principal.user_id)
    if conv is None:
        raise HTTPException(404, "conversation not found")
    conv.status = ConversationStatus.DELETED  # soft-delete, kept for audit (A4)
    from ..models import _now

    conv.deleted_at = _now()
    await session.commit()


@router.get("/conversations/{conv_id}/messages", response_model=list[MessageOut])
async def list_messages(
    conv_id: str,
    principal: Principal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
    limit: int = Query(200, le=500),
    offset: int = 0,
) -> list[Message]:
    conv = await get_owned_conversation(session, conv_id, principal.user_id)
    if conv is None:
        raise HTTPException(404, "conversation not found")
    rows = await session.scalars(
        select(Message)
        .where(
            Message.conversation_id == conv_id,
            Message.status == MessageStatus.ACTIVE,
        )
        .order_by(Message.created_at, Message.id)  # oldest-first (A3 resume)
        .limit(limit)
        .offset(offset)
    )
    return list(rows)


@router.delete("/conversations/{conv_id}/messages/{mid}", status_code=204)
async def delete_message(
    conv_id: str,
    mid: str,
    principal: Principal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
) -> None:
    conv = await get_owned_conversation(session, conv_id, principal.user_id)
    if conv is None:
        raise HTTPException(404, "conversation not found")
    msg = await session.get(Message, mid)
    if msg is None or msg.conversation_id != conv_id:
        raise HTTPException(404, "message not found")
    msg.status = MessageStatus.DELETED
    await session.commit()
