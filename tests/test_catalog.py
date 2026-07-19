from __future__ import annotations

import asyncio
import unittest
from collections.abc import Sequence
from uuid import uuid4

from larpcard.cards.catalog import CachedCardCatalog
from larpcard.cards.domain import CardTemplate, Rarity


def make_card() -> CardTemplate:
    return CardTemplate(
        id=uuid4(),
        character_name="Character",
        series_name="Series",
        aliases=(),
        image_path="artwork/card.png",
        frame_path=None,
        rarity=Rarity.COMMON,
        edition="standard",
        variant="base",
        drop_weight=1,
    )


class CountingCatalog:
    def __init__(self, cards: Sequence[CardTemplate]) -> None:
        self.cards = cards
        self.calls = 0

    async def list_active(self) -> Sequence[CardTemplate]:
        self.calls += 1
        await asyncio.sleep(0)
        return self.cards


class CatalogCacheTests(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_reads_share_one_refresh(self) -> None:
        source = CountingCatalog([make_card()])
        cache = CachedCardCatalog(source, ttl_seconds=60)

        results = await asyncio.gather(*(cache.list_active() for _ in range(20)))

        self.assertEqual(source.calls, 1)
        self.assertTrue(all(results[0] == result for result in results))

    async def test_invalidate_forces_refresh(self) -> None:
        source = CountingCatalog([make_card()])
        cache = CachedCardCatalog(source, ttl_seconds=60)
        await cache.list_active()

        await cache.invalidate()
        await cache.list_active()

        self.assertEqual(source.calls, 2)
