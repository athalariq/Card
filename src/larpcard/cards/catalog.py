from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Sequence

from larpcard.cards.domain import CardTemplate
from larpcard.drops.ports import CardCatalog


class CachedCardCatalog:
    """Short-lived process cache that prevents a database scan for every drop."""

    def __init__(
        self,
        source: CardCatalog,
        ttl_seconds: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if ttl_seconds < 1:
            raise ValueError("ttl_seconds must be positive")
        self._source = source
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._cached: tuple[CardTemplate, ...] = ()
        self._expires_at = 0.0
        self._lock = asyncio.Lock()

    async def list_active(self) -> Sequence[CardTemplate]:
        if self._cached and self._clock() < self._expires_at:
            return self._cached
        async with self._lock:
            now = self._clock()
            if self._cached and now < self._expires_at:
                return self._cached
            self._cached = tuple(await self._source.list_active())
            self._expires_at = now + self._ttl_seconds
            return self._cached

    async def invalidate(self) -> None:
        async with self._lock:
            self._cached = ()
            self._expires_at = 0.0
