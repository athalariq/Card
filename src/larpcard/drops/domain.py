from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from larpcard.cards.domain import RenderCard


class DropSlotStatus(StrEnum):
    AVAILABLE = "available"
    CLAIMED = "claimed"
    EXPIRED = "expired"


@dataclass(frozen=True, slots=True)
class DropSlot:
    id: UUID
    position: int
    card: RenderCard
    image_path: str
    frame_path: str | None
    status: DropSlotStatus = DropSlotStatus.AVAILABLE
    claimed_by: int | None = None


@dataclass(frozen=True, slots=True)
class Drop:
    id: UUID
    creator_id: int
    guild_id: int | None
    channel_id: int
    created_at: datetime
    expires_at: datetime
    slots: tuple[DropSlot, ...]
    message_id: int | None = None


@dataclass(frozen=True, slots=True)
class ClaimReceipt:
    ownership_id: UUID
    slot_id: UUID
    claimant_id: int
    character_name: str
    print_number: int
    claim_code: str
    claimed_at: datetime


class DropError(Exception):
    """Base class for expected drop errors."""


class DropCooldownError(DropError):
    def __init__(self, retry_after_seconds: int) -> None:
        self.retry_after_seconds = retry_after_seconds
        super().__init__(f"Drop cooldown: {retry_after_seconds} seconds remaining")


class CardPoolEmptyError(DropError):
    pass


class ClaimError(DropError):
    pass


class DropExpiredError(ClaimError):
    pass


class SlotAlreadyClaimedError(ClaimError):
    pass


class SlotNotFoundError(ClaimError):
    pass
