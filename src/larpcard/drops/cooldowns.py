from __future__ import annotations

import asyncio
import time
from collections.abc import Callable

from redis.asyncio import Redis


class InMemoryCooldownStore:
    """Process-local cooldown adapter used by tests and local development."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._expires_at: dict[int, float] = {}
        self._lock = asyncio.Lock()

    async def acquire(self, player_id: int, duration_seconds: int) -> tuple[bool, int]:
        if duration_seconds == 0:
            return True, 0
        async with self._lock:
            now = self._clock()
            expires_at = self._expires_at.get(player_id, 0)
            if expires_at > now:
                return False, max(1, int(expires_at - now + 0.999))
            self._expires_at[player_id] = now + duration_seconds
            return True, 0

    async def release(self, player_id: int) -> None:
        async with self._lock:
            self._expires_at.pop(player_id, None)


class RedisCooldownStore:
    """Distributed cooldown implemented as one atomic Redis SET operation."""

    def __init__(self, redis: Redis, namespace: str = "larpcard:drop:cooldown") -> None:
        self._redis = redis
        self._namespace = namespace

    async def acquire(self, player_id: int, duration_seconds: int) -> tuple[bool, int]:
        if duration_seconds == 0:
            return True, 0
        key = self._key(player_id)
        acquired = await self._redis.set(key, "1", ex=duration_seconds, nx=True)
        if acquired:
            return True, 0
        remaining = await self._redis.ttl(key)
        return False, max(1, int(remaining))

    async def release(self, player_id: int) -> None:
        await self._redis.delete(self._key(player_id))

    def _key(self, player_id: int) -> str:
        return f"{self._namespace}:{player_id}"
