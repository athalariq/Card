from __future__ import annotations

import os
import unittest
from uuid import uuid4

from redis.asyncio import Redis

from larpcard.drops.cooldowns import RedisCooldownStore

TEST_REDIS_URL = os.getenv("LARPCARD_TEST_REDIS_URL")


@unittest.skipUnless(TEST_REDIS_URL, "LARPCARD_TEST_REDIS_URL is not configured")
class RedisCooldownTests(unittest.IsolatedAsyncioTestCase):
    async def test_acquire_is_atomic_and_release_restores_access(self) -> None:
        assert TEST_REDIS_URL is not None
        redis = Redis.from_url(TEST_REDIS_URL, decode_responses=True)
        store = RedisCooldownStore(redis, namespace=f"larpcard:test:{uuid4().hex}")
        try:
            first, _ = await store.acquire(123, 30)
            second, remaining = await store.acquire(123, 30)
            await store.release(123)
            third, _ = await store.acquire(123, 30)

            self.assertTrue(first)
            self.assertFalse(second)
            self.assertGreater(remaining, 0)
            self.assertTrue(third)
        finally:
            await store.release(123)
            await redis.aclose()
