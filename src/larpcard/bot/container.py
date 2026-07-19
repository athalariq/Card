from __future__ import annotations

from dataclasses import dataclass, field

from redis.asyncio import Redis

from larpcard.cards.assets import ArtworkStore
from larpcard.cards.renderer import CardRenderer
from larpcard.config import Settings
from larpcard.database.session import Database
from larpcard.drops.service import DropService
from larpcard.economy.service import EconomyService
from larpcard.inventory.service import InventoryService
from larpcard.marketplace.service import MarketplaceService
from larpcard.trade.service import TradeService


@dataclass(slots=True)
class AppContainer:
    settings: Settings
    database: Database
    drops: DropService
    artwork: ArtworkStore
    renderer: CardRenderer
    economy: EconomyService
    inventory: InventoryService
    marketplace: MarketplaceService
    trade: TradeService
    redis: Redis | None = field(default=None)

    async def close(self) -> None:
        if self.redis is not None:
            await self.redis.aclose()
        await self.database.close()
