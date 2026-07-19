from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol
from uuid import UUID

from larpcard.cards.domain import CardTemplate
from larpcard.drops.domain import ClaimReceipt, Drop


class CardCatalog(Protocol):
    async def list_active(self) -> Sequence[CardTemplate]: ...


class DropRepository(Protocol):
    async def create(
        self,
        *,
        creator_id: int,
        guild_id: int | None,
        channel_id: int,
        templates: Sequence[CardTemplate],
        created_at: datetime,
        expires_at: datetime,
    ) -> Drop: ...

    async def bind_message(self, drop_id: UUID, message_id: int) -> None: ...

    async def claim(
        self,
        slot_id: UUID,
        claimant_id: int,
        claimed_at: datetime,
    ) -> ClaimReceipt: ...


class CooldownStore(Protocol):
    async def acquire(self, player_id: int, duration_seconds: int) -> tuple[bool, int]: ...

    async def release(self, player_id: int) -> None: ...
