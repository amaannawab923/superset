"""ExecutionController (A1 command layer) — concurrency gates + cancel flags.

Redis-backed when COPILOT_REDIS_URL is set (fast, TTL, cross-pod, per A1);
otherwise an in-memory fallback so the shell runs with zero external services.
The interface is identical either way.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from .config import get_settings

try:  # optional dependency
    import redis.asyncio as aioredis
except Exception:  # pragma: no cover
    aioredis = None  # type: ignore[assignment]

_CANCEL_TTL = 600  # seconds


class ControlPlane:
    """Concurrency gate + cancel-flag store."""

    def __init__(self) -> None:
        s = get_settings()
        self._max = s.copilot_max_concurrent_per_user
        self._redis = None
        if s.copilot_redis_url and aioredis is not None:
            self._redis = aioredis.from_url(s.copilot_redis_url, decode_responses=True)
        # in-memory fallback state
        self._counts: dict[int, int] = {}
        self._cancels: set[str] = set()
        self._lock = asyncio.Lock()

    # --- concurrency gate (A3 step 4 / release in finally at step 11) ---
    @asynccontextmanager
    async def gate(self, user_id: int):
        acquired = await self._acquire(user_id)
        if not acquired:
            raise ConcurrencyLimitExceeded(
                f"user {user_id} exceeded {self._max} concurrent generations"
            )
        try:
            yield
        finally:
            await self._release(user_id)

    async def _acquire(self, user_id: int) -> bool:
        if self._redis is not None:
            key = f"copilot:gate:{user_id}"
            n = await self._redis.incr(key)
            await self._redis.expire(key, _CANCEL_TTL)
            if n > self._max:
                await self._redis.decr(key)
                return False
            return True
        async with self._lock:
            n = self._counts.get(user_id, 0)
            if n >= self._max:
                return False
            self._counts[user_id] = n + 1
            return True

    async def _release(self, user_id: int) -> None:
        if self._redis is not None:
            await self._redis.decr(f"copilot:gate:{user_id}")
            return
        async with self._lock:
            self._counts[user_id] = max(0, self._counts.get(user_id, 1) - 1)

    # --- cancel flags (A2 /chat/cancel, polled inside the loop) ---
    async def request_cancel(self, run_id: str) -> None:
        if self._redis is not None:
            await self._redis.set(f"copilot:cancel:{run_id}", "1", ex=_CANCEL_TTL)
            return
        self._cancels.add(run_id)

    async def is_cancelled(self, run_id: str) -> bool:
        if self._redis is not None:
            return bool(await self._redis.exists(f"copilot:cancel:{run_id}"))
        return run_id in self._cancels

    async def clear_cancel(self, run_id: str) -> None:
        if self._redis is not None:
            await self._redis.delete(f"copilot:cancel:{run_id}")
            return
        self._cancels.discard(run_id)


class ConcurrencyLimitExceeded(Exception):
    pass


_control: ControlPlane | None = None


def get_control() -> ControlPlane:
    global _control
    if _control is None:
        _control = ControlPlane()
    return _control
