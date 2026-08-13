"""Pydantic request/response DTOs for the A2 routes."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from .models import AgentType, ConversationStatus, MessageRole, TitleSource


class CreateConversation(BaseModel):
    agent_type: AgentType = AgentType.DEFAULT
    title: str | None = None


class PatchConversation(BaseModel):
    title: str | None = None
    status: ConversationStatus | None = None
    pinned: bool | None = None


class MoveConversation(BaseModel):
    direction: Literal["up", "down"]


class ConversationOut(BaseModel):
    id: str
    title: str | None
    title_source: TitleSource
    agent_type: AgentType
    status: ConversationStatus
    last_message_at: datetime | None
    created_at: datetime
    message_count: int
    metadata_json: dict

    model_config = {"from_attributes": True}


class MessageOut(BaseModel):
    id: str
    conversation_id: str
    role: MessageRole
    content: str
    tool_calls: list | None
    tool_call_id: str | None
    run_id: str
    artifacts: list | None
    prompt_tokens: int
    completion_tokens: int
    created_at: datetime
    metadata_json: dict

    model_config = {"from_attributes": True}


class AttachmentOut(BaseModel):
    attachment_id: str
    filename: str


class CompletionRequest(BaseModel):
    conversation_id: str
    message: str = Field(min_length=1)
    suggested_id: str | None = None
    # Set from a prior POST .../attachments response to have this turn act
    # on the uploaded file (e.g. a .twbx routes to Migration Buddy — see
    # completion.py) regardless of the conversation's stored agent_type.
    attachment_id: str | None = None


class CancelRequest(BaseModel):
    conversation_id: str
    run_id: str | None = None
