"""File attachment storage (Migration Buddy's .twbx upload) — A2 route support.

A minimal, single-process store: an UploadFile is written to a temp dir and
tracked in an in-memory dict keyed by a generated attachment_id. This is
dev-scale on purpose (matches the LangGraph MemorySaver checkpointer's own
dev-only status per MIGRATION_BUDDY_ARCHITECTURE.md's roadmap) — a real
deployment would want durable object storage and a DB-backed record instead
of an in-memory dict that forgets everything on restart.
"""
from __future__ import annotations

import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from fastapi import UploadFile

_STORAGE_DIR = Path(tempfile.gettempdir()) / "copilot-attachments"


@dataclass
class Attachment:
    attachment_id: str
    conversation_id: str
    filename: str
    path: Path


_ATTACHMENTS: dict[str, Attachment] = {}


async def save_attachment(conversation_id: str, upload: UploadFile) -> Attachment:
    attachment_id = uuid.uuid4().hex
    conv_dir = _STORAGE_DIR / conversation_id
    conv_dir.mkdir(parents=True, exist_ok=True)
    filename = upload.filename or "upload"
    dest = conv_dir / f"{attachment_id}_{filename}"
    with dest.open("wb") as f:
        while chunk := await upload.read(1024 * 1024):
            f.write(chunk)
    attachment = Attachment(
        attachment_id=attachment_id,
        conversation_id=conversation_id,
        filename=filename,
        path=dest,
    )
    _ATTACHMENTS[attachment_id] = attachment
    return attachment


def get_attachment(attachment_id: str) -> Attachment | None:
    return _ATTACHMENTS.get(attachment_id)
