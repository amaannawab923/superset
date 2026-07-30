"""End-to-end smoke test for the base chat shell — no server, no network.

Drives the ASGI app in-process with httpx.ASGITransport:
  create conversation -> stream a completion (SSE) -> reload message history.
Run offline with COPILOT_FAKE_LLM=true (default here).
"""
from __future__ import annotations

import asyncio
import os

os.environ.setdefault("COPILOT_FAKE_LLM", "true")
os.environ.setdefault("COPILOT_MCP_ENABLED", "false")  # offline: use the stub tool
os.environ.setdefault("COPILOT_DATABASE_URL", "sqlite+aiosqlite:///./smoke.db")

import httpx  # noqa: E402

from app.db import init_db  # noqa: E402
from app.main import app  # noqa: E402


async def main() -> None:
    # fresh db
    if os.path.exists("smoke.db"):
        os.remove("smoke.db")
    await init_db()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        h = await client.get("/health")
        print("health:", h.json())

        r = await client.post(
            "/api/v1/copilot/conversations", json={"agent_type": "DEFAULT"}
        )
        conv = r.json()
        print("created conversation:", conv["id"], "title:", conv["title"])

        print("\n--- streaming /completions ---")
        events = []
        async with client.stream(
            "POST",
            "/api/v1/copilot/completions",
            json={"conversation_id": conv["id"], "message": "Hello copilot, are you there?"},
        ) as resp:
            assert resp.status_code == 200, resp.status_code
            event = None
            async for line in resp.aiter_lines():
                if line.startswith("event: "):
                    event = line[7:]
                elif line.startswith("data: "):
                    events.append((event, line[6:]))
                    tag = event or "?"
                    print(f"  [{tag}] {line[6:][:80]}")

        kinds = [e for e, _ in events]
        print("\nevent kinds:", kinds)
        assert "run_started" in kinds
        assert "token" in kinds
        assert "final" in kinds
        assert "token_status" in kinds

        m = await client.get(f"/api/v1/copilot/conversations/{conv['id']}/messages")
        msgs = m.json()
        print("\npersisted messages (A5 turn model):")
        for msg in msgs:
            print(f"  {msg['role']:>9}  run={msg['run_id'][:8]}  {msg['content'][:60]!r}")
        roles = [msg["role"] for msg in msgs]
        assert roles[0] == "USER"
        assert "ASSISTANT" in roles

        c = await client.get(f"/api/v1/copilot/conversations/{conv['id']}")
        print("\nconversation after turn:", c.json()["title"], "| msgs:", c.json()["message_count"])

    print("\nSMOKE OK")


if __name__ == "__main__":
    asyncio.run(main())
