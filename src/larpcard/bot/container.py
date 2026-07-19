from __future__ import annotations

from dataclasses import dataclass, field

from redis.asyncio import Redis

from larpcard.cards.assets import ArtworkStore
from larpcard.cards.renderer import CardRenderer
from larpcard.config import Settings
from larpcard.database.session import Database
from larpcard.drops.service import DropService


@dataclass(slots=True)
class AppContainer:
    settings: Settings
    database: Database
    drops: DropService
    artwork: ArtworkStore
    renderer: CardRenderer
    redis: Redis | None = field(default=None)

    async def close(self) -> None:
        if self.redis is not None:
            await self.redis.aclose()
        await self.database.close()
