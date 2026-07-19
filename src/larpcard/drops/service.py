from __future__ import annotations

import logging
import random
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID

from larpcard.cards.domain import CardTemplate
from larpcard.drops.domain import (
    CardPoolEmptyError,
    ClaimReceipt,
    Drop,
    DropCooldownError,
)
from larpcard.drops.ports import CardCatalog, CooldownStore, DropRepository

logger = logging.getLogger(__name__)


class DropService:
    def __init__(
        self,
        *,
        catalog: CardCatalog,
        repository: DropRepository,
        cooldowns: CooldownStore,
        minimum_cards: int,
        maximum_cards: int,
        cooldown_seconds: int,
        claim_window_seconds: int,
        rng: random.Random | None = None,
    ) -> None:
        if not 1 <= minimum_cards <= maximum_cards <= 4:
            raise ValueError("drop size must satisfy 1 <= minimum <= maximum <= 4")
        self._catalog = catalog
        self._repository = repository
        self._cooldowns = cooldowns
        self._minimum_cards = minimum_cards
        self._maximum_cards = maximum_cards
        self._cooldown_seconds = cooldown_seconds
        self._claim_window_seconds = claim_window_seconds
        self._rng = rng or random.SystemRandom()

    async def create_drop(
        self,
        *,
        creator_id: int,
        guild_id: int | None,
        channel_id: int,
        now: datetime | None = None,
        skip_cooldown: bool = False,
    ) -> Drop:
        if not skip_cooldown:
            acquired, retry_after = await self._cooldowns.acquire(
                creator_id,
                self._cooldown_seconds,
            )
            if not acquired:
                raise DropCooldownError(retry_after)

        try:
            candidates = list(await self._catalog.list_active())
            desired_count = self._rng.randint(self._minimum_cards, self._maximum_cards)
            count = min(desired_count, len(candidates))
            if count < self._minimum_cards:
                raise CardPoolEmptyError(
                    f"at least {self._minimum_cards} active card definitions are required"
                )
            selected = self._weighted_sample(candidates, count)
            created_at = now or datetime.now(UTC)
            drop = await self._repository.create(
                creator_id=creator_id,
                guild_id=guild_id,
                channel_id=channel_id,
                templates=selected,
                created_at=created_at,
                expires_at=created_at + timedelta(seconds=self._claim_window_seconds),
            )
        except Exception:
            await self._cooldowns.release(creator_id)
            raise

        logger.info(
            "drop_created",
            extra={
                "drop_id": drop.id,
                "creator_id": creator_id,
                "guild_id": guild_id,
                "card_count": len(drop.slots),
            },
        )
        return drop

    async def bind_message(self, drop_id: UUID, message_id: int) -> None:
        await self._repository.bind_message(drop_id, message_id)

    async def claim(
        self,
        *,
        slot_id: UUID,
        claimant_id: int,
        now: datetime | None = None,
    ) -> ClaimReceipt:
        receipt = await self._repository.claim(
            slot_id,
            claimant_id,
            now or datetime.now(UTC),
        )
        logger.info(
            "card_claimed",
            extra={
                "slot_id": slot_id,
                "ownership_id": receipt.ownership_id,
                "claimant_id": claimant_id,
            },
        )
        return receipt

    def _weighted_sample(
        self,
        candidates: Sequence[CardTemplate],
        count: int,
    ) -> list[CardTemplate]:
        pool = list(candidates)
        selected: list[CardTemplate] = []
        for _ in range(count):
            total_weight = sum(card.drop_weight for card in pool)
            threshold = self._rng.random() * total_weight
            cumulative = 0.0
            chosen_index = len(pool) - 1
            for index, card in enumerate(pool):
                cumulative += card.drop_weight
                if threshold < cumulative:
                    chosen_index = index
                    break
            selected.append(pool.pop(chosen_index))
        return selected
