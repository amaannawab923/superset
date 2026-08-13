"""The streaming completion route (A2 POST /completions) + cancel."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..completion import GenerateCompletionCommand
from ..control import get_control
from ..db import get_session
from ..deps import Principal, current_principal, require_feature
from ..models import ConversationStatus
from ..persistence import get_owned_conversation
from ..schemas import CancelRequest, CompletionRequest

router = APIRouter(
    prefix="/api/v1/copilot",
    tags=["copilot"],
    dependencies=[Depends(require_feature)],
)


@router.post("/completions")
async def completions(
    body: CompletionRequest,
    principal: Principal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    # @protect() equivalent: verify the user owns this chat (A3 step 2).
    conv = await get_owned_conversation(session, body.conversation_id, principal.user_id)
    if conv is None or conv.status == ConversationStatus.DELETED:
        raise HTTPException(404, "conversation not found")

    # Capture what we need while the request context is alive (A3 step 3), then
    # hand off to the command, which streams over its own session + gate.
    command = GenerateCompletionCommand(
        conv=conv,
        user_id=principal.user_id,
        user_message=body.message,
        suggested_id=body.suggested_id,
        attachment_id=body.attachment_id,
    )
    return StreamingResponse(
        command.stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Run-Id": command.run_id,
        },
    )


@router.post("/chat/cancel", status_code=202)
async def cancel(
    body: CancelRequest,
    principal: Principal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    conv = await get_owned_conversation(session, body.conversation_id, principal.user_id)
    if conv is None:
        raise HTTPException(404, "conversation not found")
    if not body.run_id:
        raise HTTPException(400, "run_id required")
    await get_control().request_cancel(body.run_id)
    return {"status": "cancelling", "run_id": body.run_id}
