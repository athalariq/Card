from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from larpcard.cards.domain import Rarity


class TradeState(StrEnum):
    PENDING = "pending"
    PLAYER1_CONFIRMED = "player1_confirmed"
    PLAYER2_CONFIRMED = "player2_confirmed"
    BOTH_CONFIRMED = "both_confirmed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class TradeCard:
    ownership_id: UUID
    definition_id: UUID
    character_name: str
    series_name: str
    rarity: Rarity
    print_number: int
    edition: str
    variant: str
    image_path: str


@dataclass(frozen=True, slots=True)
class TradeSlot:
    player_id: int
    cards: tuple[TradeCard, ...]


@dataclass(frozen=True, slots=True)
class Trade:
    id: UUID
    player1_id: int
    player2_id: int
    state: TradeState
    player1_cards: tuple[TradeCard, ...]
    player2_cards: tuple[TradeCard, ...]
    created_at: datetime
    completed_at: datetime | None

    @property
    def is_active(self) -> bool:
        return self.state not in (TradeState.COMPLETED, TradeState.CANCELLED)

    def cards_for(self, player_id: int) -> tuple[TradeCard, ...]:
        if player_id == self.player1_id:
            return self.player1_cards
        if player_id == self.player2_id:
            return self.player2_cards
        return ()


class TradeError(Exception):
    pass


class TradeNotFoundError(TradeError):
    def __init__(self, trade_id: UUID) -> None:
        self.trade_id = trade_id
        super().__init__(f"trade not found: {trade_id}")


class TradeNotParticipantError(TradeError):
    def __init__(self, trade_id: UUID, player_id: int) -> None:
        self.trade_id = trade_id
        self.player_id = player_id
        super().__init__(f"player {player_id} is not a participant in trade {trade_id}")


class TradeInvalidStateError(TradeError):
    pass


class TradeCardNotOwnedError(TradeError):
    pass
