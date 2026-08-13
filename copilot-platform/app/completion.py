"""GenerateCompletionCommand (A1 command layer, A3 lifecycle).

Standalone/async version of the reference's Flask CQRS command: because the
whole stack is async (FastAPI + LangGraph + async SQLAlchemy) there is no
daemon-thread/Queue async<->sync bridge to build. The command still owns the
turn: hold the concurrency gate, save the USER row, run the agent_node<->tools_node
loop, stream SSE token/tool events, persist the A5 four-row turn, and release the
gate in a finally.
"""
from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncIterator

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage

from .agent.graph import RECURSION_LIMIT, get_graph_for
from .agent.llm import DEFAULT_TITLE, generate_title
from .agent.migration.freeform import run_freeform_migration
from .attachments import Attachment, get_attachment
from .config import get_settings
from .control import ConcurrencyLimitExceeded, get_control
from .db import SessionLocal
from .models import AgentType, Conversation, MessageRole, TitleSource
from .persistence import (
    add_message,
    load_history,
    set_system_title,
    touch_conversation,
)

logger = logging.getLogger(__name__)

_MIGRATION_EXTENSIONS = (".twbx",)


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):  # Anthropic block list
        return "".join(
            b.get("text", "")
            for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        )
    return ""


class GenerateCompletionCommand:
    def __init__(
        self,
        conv: Conversation,
        user_id: int,
        user_message: str,
        suggested_id: str | None,
        attachment_id: str | None = None,
    ):
        self.conv_id = conv.id
        self.thread_id = conv.thread_id
        self.agent_type = conv.agent_type
        self.user_id = user_id
        self.user_message = user_message
        self.suggested_id = suggested_id
        self.attachment_id = attachment_id
        self.run_id = uuid.uuid4().hex

    async def stream(self) -> AsyncIterator[str]:
        control = get_control()
        try:
            async with control.gate(self.user_id):
                async for chunk in self._run():
                    yield chunk
        except ConcurrencyLimitExceeded as exc:
            yield _sse("error", {"run_id": self.run_id, "message": str(exc)})
        finally:
            await control.clear_cancel(self.run_id)

    # A completion runs in its own DB session (the request session is gone by the
    # time the StreamingResponse body is consumed).
    async def _run(self) -> AsyncIterator[str]:
        control = get_control()
        async with SessionLocal() as session:
            conv = await session.get(Conversation, self.conv_id)
            if conv is None:
                yield _sse("error", {"message": "conversation not found"})
                return

            # step 4: save the USER message immediately.
            first_turn = conv.message_count == 0
            await add_message(
                session,
                conv=conv,
                run_id=self.run_id,
                role=MessageRole.USER,
                content=self.user_message,
                suggested_id=self.suggested_id,
            )
            if first_turn:
                # Fixed, neutral placeholder — never the user's own raw
                # message — replaced with an LLM-generated title once the
                # assistant's first reply is in, below.
                set_system_title(conv, DEFAULT_TITLE)
            await session.commit()

            yield _sse("run_started", {"run_id": self.run_id, "conversation_id": conv.id})

            # Routing is attachment-triggered, not persona-pre-selection-
            # triggered: any conversation that gets a .twbx attached runs
            # Migration Buddy for that turn, regardless of conv.agent_type.
            attachment = get_attachment(self.attachment_id) if self.attachment_id else None
            if attachment and attachment.filename.lower().endswith(_MIGRATION_EXTENSIONS):
                async for chunk in self._run_migration(session, conv, attachment):
                    yield chunk
                return

            history = await load_history(session, conv.id)
            graph = await get_graph_for(self.agent_type)
            config = {
                "configurable": {"thread_id": self.thread_id},
                "recursion_limit": RECURSION_LIMIT,
            }

            prompt_tokens = 0
            completion_tokens = 0
            cancelled = False

            async for mode, chunk in graph.astream(
                {"messages": history}, config=config, stream_mode=["messages", "updates"]
            ):
                if await control.is_cancelled(self.run_id):
                    cancelled = True
                    break

                if mode == "messages":
                    msg, meta = chunk
                    if (
                        isinstance(msg, AIMessageChunk)
                        and meta.get("langgraph_node") == "agent"
                    ):
                        text = _text_of(msg.content)
                        if text:
                            yield _sse("token", {"run_id": self.run_id, "text": text})

                elif mode == "updates":
                    for _node, payload in chunk.items():
                        for m in payload.get("messages", []):
                            if isinstance(m, AIMessage):
                                usage = getattr(m, "usage_metadata", None) or {}
                                prompt_tokens += usage.get("input_tokens", 0)
                                completion_tokens += usage.get("output_tokens", 0)
                                if m.tool_calls:
                                    # A5 row 2: ASSISTANT tool-request
                                    await add_message(
                                        session,
                                        conv=conv,
                                        run_id=self.run_id,
                                        role=MessageRole.ASSISTANT,
                                        content=_text_of(m.content),
                                        tool_calls=[
                                            {
                                                "id": tc["id"],
                                                "name": tc["name"],
                                                "arguments": tc["args"],
                                            }
                                            for tc in m.tool_calls
                                        ],
                                    )
                                    for tc in m.tool_calls:
                                        yield _sse(
                                            "tool_call",
                                            {
                                                "run_id": self.run_id,
                                                "id": tc["id"],
                                                "name": tc["name"],
                                                "arguments": tc["args"],
                                            },
                                        )
                                else:
                                    # A5 row 4: ASSISTANT final answer. Artifacts
                                    # (e.g. a chart the agent just created) ride
                                    # in additional_kwargs — see
                                    # claude_sdk_llm.py's _astream, the only
                                    # producer today since bind_tools() there is
                                    # a no-op and LangGraph's own tools_node
                                    # never fires on that path.
                                    artifacts = m.additional_kwargs.get("artifacts") or None
                                    await add_message(
                                        session,
                                        conv=conv,
                                        run_id=self.run_id,
                                        role=MessageRole.ASSISTANT,
                                        content=_text_of(m.content),
                                        artifacts=artifacts,
                                        prompt_tokens=usage.get("input_tokens", 0),
                                        completion_tokens=usage.get("output_tokens", 0),
                                        metadata={"stop_reason": "end_turn"},
                                    )
                                    if artifacts:
                                        yield _sse(
                                            "artifacts",
                                            {"run_id": self.run_id, "artifacts": artifacts},
                                        )
                                    yield _sse(
                                        "final",
                                        {
                                            "run_id": self.run_id,
                                            "content": _text_of(m.content),
                                        },
                                    )
                                    # Re-derive the title from *this* turn's
                                    # exchange after every reply, not just the
                                    # first — keeps it reflecting the recent
                                    # request rather than freezing on however
                                    # the conversation opened. An explicit
                                    # user rename (title_source=USER) is the
                                    # only thing that stops this.
                                    if conv.title_source != TitleSource.USER:
                                        title = await generate_title(
                                            self.user_message, _text_of(m.content)
                                        )
                                        set_system_title(conv, title)
                                        await session.commit()
                                        yield _sse(
                                            "title",
                                            {"run_id": self.run_id, "title": conv.title},
                                        )
                            elif isinstance(m, ToolMessage):
                                # A5 row 3: TOOL result
                                await add_message(
                                    session,
                                    conv=conv,
                                    run_id=self.run_id,
                                    role=MessageRole.TOOL,
                                    content=str(m.content),
                                    tool_call_id=m.tool_call_id,
                                )
                                yield _sse(
                                    "tool_result",
                                    {
                                        "run_id": self.run_id,
                                        "tool_call_id": m.tool_call_id,
                                        "content": str(m.content),
                                    },
                                )

            await touch_conversation(session, conv)
            await session.commit()

            yield _sse(
                "usage",
                {
                    "run_id": self.run_id,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                },
            )
            yield _sse(
                "token_status",
                {"run_id": self.run_id, "status": "cancelled" if cancelled else "done"},
            )

    async def _run_migration(
        self, session, conv: Conversation, attachment: Attachment
    ) -> AsyncIterator[str]:
        """Migration Buddy's turn: stream migration_progress narration as
        the free-form migration agent (app/agent/migration/freeform.py — a
        real Claude Agent SDK session with Bash/Read/Write, hitting
        Superset's REST API directly with its own judgment, no fixed IR)
        works through the workbook, then persist a final ASSISTANT message
        carrying its "## Report" text. Every stage also goes to the server
        log at INFO, tagged with run_id, so `tail -f` on the backend
        process shows the same trace the SSE stream sends the UI — useful
        for watching each tool call the agent makes without instrumenting
        the UI further.

        This deliberately does not run the deterministic pipeline
        (migration_graph.run_migration — parsing.py/analyst.py/verify.py/
        apply.py/calc_ir.py) — that pipeline still exists and still works
        for the tiles it covers, but on real-world workbooks with table
        calcs, date functions, or calc-chain filters it has no vocabulary
        for, it stalls at 0 buildable tiles. A free-form agent proved out
        as a one-off POC on exactly that failure case (MerchandiseSales:
        0/18 deterministic vs. 23 charts across all 22 real tiles
        free-form) — see freeform.py's docstring for what that POC found,
        including two bugs it caught by reading real data rather than
        trusting labels/formula names. Trade-off made explicit there too:
        this path has no independent oracle-verification gate.
        """
        conv.agent_type = AgentType.MIGRATION
        await session.commit()
        logger.info(
            "Migration Buddy [%s]: starting %r (conversation %s)",
            self.run_id, attachment.filename, conv.id,
        )

        s = get_settings()
        final_detail = ""
        report: dict | None = None
        dashboard: dict | None = None

        async for event in run_freeform_migration(
            str(attachment.path),
            attachment.filename,
            s.copilot_migration_database_id,
            s.copilot_migration_superset_base_url,
            s.copilot_migration_superset_admin_user,
            s.copilot_migration_superset_admin_password,
        ):
            final_detail = event["detail"]
            logger.info(
                "Migration Buddy [%s]: %s | %s | %s | %s",
                self.run_id, event["stage"], event.get("tile") or "-",
                event.get("verdict") or "-", event["detail"],
            )
            yield _sse(
                "migration_progress",
                {
                    "run_id": self.run_id,
                    "stage": event["stage"],
                    "tile": event.get("tile"),
                    "verdict": event.get("verdict"),
                    "detail": event["detail"],
                },
            )
            if event["stage"] == "done":
                report = event.get("report")
                dashboard = event.get("dashboard")

        if report:
            logger.info(
                "Migration Buddy [%s]: finished %r — GREEN=%d YELLOW=%d RED=%d",
                self.run_id, attachment.filename,
                report["GREEN"], report["YELLOW"], report["RED"],
            )

        artifacts = None
        if dashboard:
            artifacts = [
                {
                    "type": "dashboard",
                    "id": dashboard["id"],
                    "name": dashboard.get("dashboard_title") or attachment.filename,
                    "url": dashboard.get("url"),
                }
            ]

        summary = final_detail
        if report:
            summary = (
                f"Migrated **{attachment.filename}**: {report['GREEN']} chart(s) verified, "
                f"{report['YELLOW']} built but unverified, {report['RED']} flagged and "
                f"skipped.\n\n{final_detail}"
            )

        await add_message(
            session,
            conv=conv,
            run_id=self.run_id,
            role=MessageRole.ASSISTANT,
            content=summary,
            artifacts=artifacts,
            metadata={"stop_reason": "end_turn", "migration_report": report},
        )
        await session.commit()

        if artifacts:
            yield _sse("artifacts", {"run_id": self.run_id, "artifacts": artifacts})
        yield _sse("final", {"run_id": self.run_id, "content": summary})

        if conv.title_source != TitleSource.USER:
            title = await generate_title(self.user_message, summary)
            set_system_title(conv, title)
            await session.commit()
            yield _sse("title", {"run_id": self.run_id, "title": conv.title})

        await touch_conversation(session, conv)
        await session.commit()

        yield _sse(
            "usage", {"run_id": self.run_id, "prompt_tokens": 0, "completion_tokens": 0}
        )
        yield _sse("token_status", {"run_id": self.run_id, "status": "done"})
