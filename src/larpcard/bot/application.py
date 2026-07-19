from __future__ import annotations

import logging

import discord
from discord.ext import commands
from redis.asyncio import Redis

from larpcard.bot.cogs.admin import AdminCog
from larpcard.bot.cogs.drops import DropsCog
from larpcard.bot.cogs.inventory import InventoryCog
from larpcard.bot.cogs.marketplace import MarketplaceCog
from larpcard.bot.cogs.profile import ProfileCog
from larpcard.bot.cogs.rewards import RewardsCog
from larpcard.bot.cogs.trade import TradeCog
from larpcard.bot.container import AppContainer
from larpcard.cards.assets import LocalArtworkStore
from larpcard.cards.catalog import CachedCardCatalog
from larpcard.cards.renderer import CardRenderer
from larpcard.config import Settings
from larpcard.database.base import Base
from larpcard.database.repositories import (
    SqlAlchemyBalanceStore,
    SqlAlchemyCardCatalog,
    SqlAlchemyDropRepository,
    SqlAlchemyInventoryQuery,
    SqlAlchemyMarketplaceRepository,
    SqlAlchemyRewardStore,
    SqlAlchemyTradeRepository,
    SqlAlchemyTransactionLog,
)
from larpcard.database.session import Database
from larpcard.drops.cooldowns import InMemoryCooldownStore, RedisCooldownStore
from larpcard.drops.ports import CooldownStore
from larpcard.drops.service import DropService
from larpcard.economy.service import EconomyService
from larpcard.inventory.service import InventoryService
from larpcard.marketplace.service import MarketplaceService
from larpcard.trade.service import TradeService

logger = logging.getLogger(__name__)


class LarpCardBot(commands.Bot):
    def __init__(self, settings: Settings) -> None:
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=discord.Intents.default(),
            allowed_mentions=discord.AllowedMentions(
                users=True,
                roles=False,
                everyone=False,
                replied_user=False,
            ),
        )
        self.settings = settings
        self.container: AppContainer | None = None

    async def setup_hook(self) -> None:
        database = Database.connect(self.settings.database_url)
        async with database.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        redis: Redis | None = None
        cooldowns: CooldownStore
        try:
            client = Redis.from_url(self.settings.redis_url, decode_responses=True)
            await client.ping()
            redis = client
            cooldowns = RedisCooldownStore(client)
        except Exception:
            logger.warning("redis_unavailable_falling_back_to_in_memory_cooldowns")
            cooldowns = InMemoryCooldownStore()
        catalog = CachedCardCatalog(
            SqlAlchemyCardCatalog(database.sessions),
            ttl_seconds=self.settings.catalog_cache_seconds,
        )
        repository = SqlAlchemyDropRepository(database.sessions)
        drop_service = DropService(
            catalog=catalog,
            repository=repository,
            cooldowns=cooldowns,
            minimum_cards=self.settings.drop_min_cards,
            maximum_cards=self.settings.drop_max_cards,
            cooldown_seconds=self.settings.drop_cooldown_seconds,
            claim_window_seconds=self.settings.claim_window_seconds,
        )
        economy_service = EconomyService(
            balances=SqlAlchemyBalanceStore(database.sessions),
            transactions=SqlAlchemyTransactionLog(database.sessions),
            rewards=SqlAlchemyRewardStore(database.sessions),
        )
        marketplace_service = MarketplaceService(
            repository=SqlAlchemyMarketplaceRepository(database.sessions),
            economy=economy_service,
        )
        self.container = AppContainer(
            settings=self.settings,
            database=database,
            drops=drop_service,
            artwork=LocalArtworkStore(self.settings.asset_root),
            renderer=CardRenderer(self.settings.asset_root),
            economy=economy_service,
            inventory=InventoryService(query=SqlAlchemyInventoryQuery(database.sessions)),
            marketplace=marketplace_service,
            trade=TradeService(repository=SqlAlchemyTradeRepository(database.sessions)),
            redis=redis,
        )
        await self.add_cog(DropsCog(self.container))
        await self.add_cog(AdminCog(self.container, self))
        await self.add_cog(RewardsCog(self.container))
        await self.add_cog(InventoryCog(self.container))
        await self.add_cog(MarketplaceCog(self.container))
        await self.add_cog(TradeCog(self.container))
        await self.add_cog(ProfileCog(self.container))
        if self.settings.sync_commands_on_startup:
            if self.settings.dev_guild_ids:
                for guild_id in self.settings.dev_guild_ids:
                    self.tree.copy_global_to(guild=discord.Object(id=guild_id))
                    synced = await self.tree.sync(guild=discord.Object(id=guild_id))
                    logger.info(
                        "guild_commands_synced",
                        extra={"guild_id": guild_id, "count": len(synced)},
                    )
            else:
                synced = await self.tree.sync()
                logger.info("global_commands_synced", extra={"count": len(synced)})

    async def close(self) -> None:
        try:
            if self.container is not None:
                await self.container.close()
        finally:
            await super().close()
