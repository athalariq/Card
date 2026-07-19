from __future__ import annotations

import asyncio
import os
import random
import unittest
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from larpcard.cards.domain import Rarity
from larpcard.database.base import Base
from larpcard.database.models import CardDefinitionModel, CharacterModel, SeriesModel
from larpcard.database.repositories import SqlAlchemyCardCatalog, SqlAlchemyDropRepository
from larpcard.database.session import Database
from larpcard.drops.cooldowns import InMemoryCooldownStore
from larpcard.drops.domain import ClaimReceipt, SlotAlreadyClaimedError
from larpcard.drops.service import DropService

TEST_DATABASE_URL = os.getenv("LARPCARD_TEST_DATABASE_URL")


@unittest.skipUnless(TEST_DATABASE_URL, "LARPCARD_TEST_DATABASE_URL is not configured")
class PostgreSqlClaimTests(unittest.IsolatedAsyncioTestCase):
    admin_engine: AsyncEngine
    database: Database
    schema: str

    async def asyncSetUp(self) -> None:
        assert TEST_DATABASE_URL is not None
        self.schema = f"larpcard_test_{uuid4().hex}"
        self.admin_engine = create_async_engine(TEST_DATABASE_URL)
        async with self.admin_engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{self.schema}"'))

        test_engine = create_async_engine(
            TEST_DATABASE_URL,
            connect_args={"server_settings": {"search_path": self.schema}},
            pool_pre_ping=True,
        )
        self.database = Database(
            engine=test_engine,
            sessions=async_sessionmaker[AsyncSession](
                test_engine,
                expire_on_commit=False,
            ),
        )
        async with test_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def asyncTearDown(self) -> None:
        await self.database.close()
        async with self.admin_engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{self.schema}" CASCADE'))
        await self.admin_engine.dispose()

    async def test_postgresql_row_lock_allows_exactly_one_claim(self) -> None:
        await self._seed_catalog()
        repository = SqlAlchemyDropRepository(self.database.sessions)
        service = DropService(
            catalog=SqlAlchemyCardCatalog(self.database.sessions),
            repository=repository,
            cooldowns=InMemoryCooldownStore(),
            minimum_cards=2,
            maximum_cards=2,
            cooldown_seconds=0,
            claim_window_seconds=60,
            rng=random.Random(4),
        )
        now = datetime.now(UTC)
        drop = await service.create_drop(
            creator_id=100,
            guild_id=200,
            channel_id=300,
            now=now,
        )

        results = await asyncio.gather(
            service.claim(slot_id=drop.slots[0].id, claimant_id=501, now=now),
            service.claim(slot_id=drop.slots[0].id, claimant_id=502, now=now),
            return_exceptions=True,
        )

        self.assertEqual(sum(isinstance(result, ClaimReceipt) for result in results), 1)
        self.assertEqual(
            sum(isinstance(result, SlotAlreadyClaimedError) for result in results),
            1,
        )

    async def _seed_catalog(self) -> None:
        async with self.database.sessions() as session, session.begin():
            series = SeriesModel(name="Test Series", slug=f"test-series-{uuid4().hex}")
            session.add(series)
            await session.flush()
            for index in range(3):
                character = CharacterModel(
                    series_id=series.id,
                    name=f"Character {index}",
                    aliases=[],
                )
                session.add(character)
                await session.flush()
                session.add(
                    CardDefinitionModel(
                        character_id=character.id,
                        image_path=f"artwork/{index}.png",
                        rarity=Rarity.COMMON,
                        edition="standard",
                        variant="base",
                        tags=[],
                        drop_weight=1,
                    )
                )
