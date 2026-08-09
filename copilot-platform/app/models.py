"""SQLAlchemy models — the A4 schema, verbatim.

copilot_conversations (one row = one chat thread)
copilot_messages      (one row = one message; the conversation memory)

Portability note: UUIDs and timestamps are stored as portable column types so
the same models run on SQLite (dev) and Postgres (prod). In prod, switch the id
columns to native UUID and add the indexes called out in A4.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --- enums (A4) ---
class TitleSource(str, enum.Enum):
    SYSTEM = "SYSTEM"
    USER = "USER"


class AgentType(str, enum.Enum):
    # Base personas (A4) ...
    DEFAULT = "DEFAULT"
    SQL_EXPERT = "SQL_EXPERT"
    EXPERIMENTATION = "EXPERIMENTATION"
    # ... extended for the multi-agent platform (Part B1).
    DATA_EXPLORATION = "DATA_EXPLORATION"
    MIGRATION = "MIGRATION"


class ConversationStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"
    DELETED = "DELETED"


class MessageRole(str, enum.Enum):
    USER = "USER"
    ASSISTANT = "ASSISTANT"
    SYSTEM = "SYSTEM"
    TOOL = "TOOL"


class MessageStatus(str, enum.Enum):
    ACTIVE = "active"
    DELETED = "deleted"


class Conversation(Base):
    __tablename__ = "copilot_conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    workspace_id: Mapped[str] = mapped_column(String(128), index=True)
    thread_id: Mapped[str] = mapped_column(String(64), unique=True, default=_uuid)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title_source: Mapped[TitleSource] = mapped_column(
        Enum(TitleSource), default=TitleSource.SYSTEM
    )
    agent_type: Mapped[AgentType] = mapped_column(
        Enum(AgentType), default=AgentType.DEFAULT
    )
    status: Mapped[ConversationStatus] = mapped_column(
        Enum(ConversationStatus), default=ConversationStatus.ACTIVE, index=True
    )
    last_message_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", lazy="selectin"
    )


class Message(Base):
    __tablename__ = "copilot_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    conversation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("copilot_conversations.id"), index=True
    )
    workspace_id: Mapped[str] = mapped_column(String(128))
    role: Mapped[MessageRole] = mapped_column(Enum(MessageRole))
    content: Mapped[str] = mapped_column(Text, default="")
    tool_calls: Mapped[list | None] = mapped_column(JSON, nullable=True)
    tool_call_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[MessageStatus] = mapped_column(
        Enum(MessageStatus), default=MessageStatus.ACTIVE, index=True
    )
    artifacts: Mapped[list | None] = mapped_column(JSON, nullable=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Numeric(12, 6), default=0)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    suggested_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, index=True
    )

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")


# oldest-first replay of one conversation (A3 step: load history on resume)
Index("ix_msg_conv_created", Message.conversation_id, Message.created_at)
