from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from uuid import UUID


class CurrencyType(StrEnum):
    COINS = "coins"
    GEMS = "gems"
    EVENT_TOKENS = "event_tokens"


class TransactionType(StrEnum):
    DAILY_REWARD = "daily_reward"
    WEEKLY_REWARD = "weekly_reward"
    ACHIEVEMENT = "achievement"
    MARKETPLACE_SALE = "marketplace_sale"
    MARKETPLACE_PURCHASE = "marketplace_purchase"
    TRADE = "trade"
    EVENT_REWARD = "event_reward"
    ADMIN_GRANT = "admin_grant"
    ADMIN_REMOVE = "admin_remove"
    MISSION_REWARD = "mission_reward"


class RewardType(StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"
    ACHIEVEMENT = "achievement"
    MISSION = "mission"
    EVENT = "event"
    BONUS = "bonus"


@dataclass(frozen=True, slots=True)
class Balance:
    coins: int
    gems: int
    event_tokens: int

    def has_at_least(self, currency: CurrencyType, amount: int) -> bool:
        match currency:
            case CurrencyType.COINS:
                return self.coins >= amount
            case CurrencyType.GEMS:
                return self.gems >= amount
            case CurrencyType.EVENT_TOKENS:
                return self.event_tokens >= amount

    def with_addition(self, currency: CurrencyType, amount: int) -> Balance:
        match currency:
            case CurrencyType.COINS:
                return Balance(self.coins + amount, self.gems, self.event_tokens)
            case CurrencyType.GEMS:
                return Balance(self.coins, self.gems + amount, self.event_tokens)
            case CurrencyType.EVENT_TOKENS:
                return Balance(self.coins, self.gems, self.event_tokens + amount)

    def with_subtraction(self, currency: CurrencyType, amount: int) -> Balance:
        match currency:
            case CurrencyType.COINS:
                return Balance(self.coins - amount, self.gems, self.event_tokens)
            case CurrencyType.GEMS:
                return Balance(self.coins, self.gems - amount, self.event_tokens)
            case CurrencyType.EVENT_TOKENS:
                return Balance(self.coins, self.gems, self.event_tokens - amount)


@dataclass(frozen=True, slots=True)
class Transaction:
    id: UUID
    player_id: int
    transaction_type: TransactionType
    currency: CurrencyType
    amount: int
    balance_after: int
    reference_id: str | None
    description: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class RewardClaim:
    id: UUID
    player_id: int
    reward_type: RewardType
    currency: CurrencyType
    amount: int
    streak: int
    claimed_at: datetime
    claim_date: date | None = None


@dataclass(frozen=True, slots=True)
class RewardAvailability:
    """Read model describing a player's standing for a repeatable reward."""

    reward_type: RewardType
    streak: int
    on_cooldown: bool
    next_available: date


class EconomyError(Exception):
    pass


class InsufficientFundsError(EconomyError):
    def __init__(self, currency: CurrencyType, requested: int, available: int) -> None:
        self.currency = currency
        self.requested = requested
        self.available = available
        super().__init__(
            f"insufficient {currency.value}: requested {requested}, have {available}"
        )


class RewardAlreadyClaimedError(EconomyError):
    def __init__(
        self,
        message: str = "reward already claimed",
        *,
        next_available: date | None = None,
    ) -> None:
        self.next_available = next_available
        super().__init__(message)


class NegativeAmountError(EconomyError):
    pass
