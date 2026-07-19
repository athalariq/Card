from __future__ import annotations

import asyncio
import random
import unittest
from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID, uuid4

from larpcard.cards.domain import CardTemplate, Rarity, RenderCard
from larpcard.drops.cooldowns import InMemoryCooldownStore
from larpcard.drops.domain import (
    CardPoolEmptyError,
    ClaimReceipt,
    Drop,
    DropCooldownError,
    DropExpiredError,
    DropSlot,
    DropSlotStatus,
    SlotAlreadyClaimedError,
)
from larpcard.drops.service import DropService


def make_card(index: int, weight: float = 1.0) -> CardTemplate:
    return CardTemplate(
        id=uuid4(),
        character_name=f"Character {index}",
        series_name=f"Series {index % 2}",
        aliases=(),
        image_path=f"artwork/{index}.png",
        frame_path=None,
        rarity=Rarity.LEGENDARY if index == 0 else Rarity.COMMON,
        edition="standard",
        variant="base",
        drop_weight=weight,
    )


class StaticCatalog:
    def __init__(self, cards: Sequence[CardTemplate]) -> None:
        self.cards = cards

    async def list_active(self) -> Sequence[CardTemplate]:
        return self.cards


class MemoryDropRepository:
    def __init__(self, *, fail_create: bool = False) -> None:
        self.fail_create = fail_create
        self.created: list[Drop] = []
        self.bound_messages: dict[UUID, int] = {}
        self._slots: dict[UUID, tuple[DropSlot, datetime]] = {}
        self._lock = asyncio.Lock()
        self._prints: dict[UUID, int] = {}

    async def create(
        self,
        *,
        creator_id: int,
        guild_id: int | None,
        channel_id: int,
        templates: Sequence[CardTemplate],
        created_at: datetime,
        expires_at: datetime,
    ) -> Drop:
        if self.fail_create:
            raise RuntimeError("database unavailable")
        slots = []
        for position, template in enumerate(templates):
            print_number = self._prints.get(template.id, 1)
            self._prints[template.id] = print_number + 1
            slot = DropSlot(
                id=uuid4(),
                position=position,
                card=RenderCard(
                    template_id=template.id,
                    character_name=template.character_name,
                    series_name=template.series_name,
                    rarity=template.rarity,
                    print_number=print_number,
                    edition=template.edition,
                    variant=template.variant,
                ),
                image_path=template.image_path,
                frame_path=template.frame_path,
            )
            slots.append(slot)
            self._slots[slot.id] = (slot, expires_at)
        drop = Drop(
            id=uuid4(),
            creator_id=creator_id,
            guild_id=guild_id,
            channel_id=channel_id,
            created_at=created_at,
            expires_at=expires_at,
            slots=tuple(slots),
        )
        self.created.append(drop)
        return drop

    async def bind_message(self, drop_id: UUID, message_id: int) -> None:
        self.bound_messages[drop_id] = message_id

    async def claim(
        self,
        slot_id: UUID,
        claimant_id: int,
        claimed_at: datetime,
    ) -> ClaimReceipt:
        async with self._lock:
            slot, expires_at = self._slots[slot_id]
            if claimed_at >= expires_at:
                raise DropExpiredError
            if slot.status is not DropSlotStatus.AVAILABLE:
                raise SlotAlreadyClaimedError
            claimed = DropSlot(
                id=slot.id,
                position=slot.position,
                card=slot.card,
                image_path=slot.image_path,
                frame_path=slot.frame_path,
                status=DropSlotStatus.CLAIMED,
                claimed_by=claimant_id,
            )
            self._slots[slot_id] = (claimed, expires_at)
            ownership_id = uuid4()
            return ClaimReceipt(
                ownership_id=ownership_id,
                slot_id=slot_id,
                claimant_id=claimant_id,
                character_name=slot.card.character_name,
                print_number=slot.card.print_number,
                claim_code=ownership_id.hex[:6],
                claimed_at=claimed_at,
            )


class DropServiceTests(unittest.IsolatedAsyncioTestCase):
    def make_service(
        self,
        cards: Sequence[CardTemplate],
        repository: MemoryDropRepository | None = None,
        cooldowns: InMemoryCooldownStore | None = None,
    ) -> tuple[DropService, MemoryDropRepository, InMemoryCooldownStore]:
        repository = repository or MemoryDropRepository()
        cooldowns = cooldowns or InMemoryCooldownStore()
        return (
            DropService(
                catalog=StaticCatalog(cards),
                repository=repository,
                cooldowns=cooldowns,
                minimum_cards=3,
                maximum_cards=3,
                cooldown_seconds=60,
                claim_window_seconds=30,
                rng=random.Random(17),
            ),
            repository,
            cooldowns,
        )

    async def test_drop_has_configured_size_and_no_duplicate_definitions(self) -> None:
        service, _, _ = self.make_service([make_card(index) for index in range(6)])

        drop = await service.create_drop(
            creator_id=100,
            guild_id=200,
            channel_id=300,
        )

        self.assertEqual(len(drop.slots), 3)
        self.assertEqual(len({slot.card.template_id for slot in drop.slots}), 3)
        self.assertEqual([slot.position for slot in drop.slots], [0, 1, 2])

    async def test_cooldown_blocks_second_drop(self) -> None:
        service, _, _ = self.make_service([make_card(index) for index in range(6)])
        await service.create_drop(creator_id=100, guild_id=200, channel_id=300)

        with self.assertRaises(DropCooldownError):
            await service.create_drop(creator_id=100, guild_id=200, channel_id=300)

    async def test_failed_creation_releases_cooldown(self) -> None:
        cards = [make_card(index) for index in range(6)]
        repository = MemoryDropRepository(fail_create=True)
        cooldowns = InMemoryCooldownStore()
        service, _, _ = self.make_service(cards, repository, cooldowns)

        with self.assertRaises(RuntimeError):
            await service.create_drop(creator_id=100, guild_id=200, channel_id=300)
        repository.fail_create = False

        drop = await service.create_drop(creator_id=100, guild_id=200, channel_id=300)

        self.assertEqual(len(drop.slots), 3)

    async def test_small_pool_fails_and_releases_cooldown(self) -> None:
        service, _, _ = self.make_service([make_card(1), make_card(2)])

        with self.assertRaises(CardPoolEmptyError):
            await service.create_drop(creator_id=100, guild_id=200, channel_id=300)
        with self.assertRaises(CardPoolEmptyError):
            await service.create_drop(creator_id=100, guild_id=200, channel_id=300)

    async def test_only_one_concurrent_claim_succeeds(self) -> None:
        service, _, _ = self.make_service([make_card(index) for index in range(6)])
        now = datetime.now(UTC)
        drop = await service.create_drop(
            creator_id=100,
            guild_id=200,
            channel_id=300,
            now=now,
        )
        slot_id = drop.slots[0].id

        results = await asyncio.gather(
            service.claim(slot_id=slot_id, claimant_id=501, now=now),
            service.claim(slot_id=slot_id, claimant_id=502, now=now),
            return_exceptions=True,
        )

        successes = [result for result in results if isinstance(result, ClaimReceipt)]
        failures = [result for result in results if isinstance(result, SlotAlreadyClaimedError)]
        self.assertEqual(len(successes), 1)
        self.assertEqual(len(failures), 1)
