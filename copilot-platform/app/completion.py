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
from .agent.migration import parsing
from .agent.migration import tableau_parse as tp
from .attachments import Attachment, get_attachment
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


def _describe_workbook_context(attachment: Attachment) -> str | None:
    """Reverse-engineer every tab/tile in an attached .twbx into a compact,
    LLM-readable block, appended to the user's own message so the *existing*
    chat agent narrates it — not a hardcoded template. Deliberately the ONLY
    thing a .twbx attachment triggers right now: the verify/apply pipeline
    (migration_graph.run_migration) needs a packaged extract and a lot more
    trust before it should run unprompted on every upload, so for this pass
    an attachment gets reconnaissance, not an attempted migration. Returns
    None on a file this build can't even parse — the caller falls back to
    telling the LLM that plainly rather than crashing the turn.
    """
    try:
        root, inst, formulas, _frames = tp.load_workbook(str(attachment.path))
        tabs = parsing.describe_workbook(root, inst, formulas)
    except Exception:  # noqa: BLE001 — a bad upload must flag, not crash the turn
        logger.exception("Migration Buddy: failed to parse workbook for description")
        return (
            f"[Attached file {attachment.filename!r} could not be parsed as a "
            "Tableau .twbx — tell the user it looks corrupted or isn't a "
            "packaged Tableau workbook.]"
        )

    lines = [f"[Parsed {attachment.filename!r} — {len(tabs)} dashboard tab(s):"]
    for tab in tabs:
        real_tiles = [t for t in tab["tiles"] if t["type"] not in ("decoration", "text/label")]
        deco_count = len(tab["tiles"]) - len(real_tiles)
        lines.append(f"\nTab {tab['name']!r} ({len(real_tiles)} chart tile(s)"
                      f"{f', {deco_count} decoration/label element(s)' if deco_count else ''}):")
        for t in real_tiles:
            bits = [t["type"]]
            if t["measures"]:
                bits.append("measures: " + ", ".join(t["measures"]))
            if t["dims"]:
                bits.append("dims: " + ", ".join(t["dims"]))
            if t["uses_calc"]:
                bits.append("uses a calculated field")
            lines.append(f"  - {t['name']!r}: {'; '.join(bits)}")
    lines.append(
        "\nThis is reconnaissance only — nothing has been migrated or verified "
        "yet. Summarize this back to the user tab by tab in plain language "
        "(what kind of chart each tile is, what it measures), the way a "
        "colleague would describe a dashboard they just opened. Do not claim "
        "anything was migrated, verified, or built.]"
    )
    return "\n".join(lines)


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
            workbook_context: str | None = None
            if attachment and attachment.filename.lower().endswith(_MIGRATION_EXTENSIONS):
                conv.agent_type = AgentType.MIGRATION
                await session.commit()
                workbook_context = _describe_workbook_context(attachment)

            history = await load_history(session, conv.id)
            if workbook_context and history and isinstance(history[-1], HumanMessage):
                # Augment only the in-memory copy the LLM sees this turn —
                # the persisted USER row stays the user's own clean text.
                history[-1] = HumanMessage(
                    content=f"{history[-1].content}\n\n{workbook_context}"
                )
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
