from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from typing import Protocol
from uuid import UUID

from larpcard.economy.domain import (
    Balance,
    CurrencyType,
    RewardClaim,
    RewardType,
    Transaction,
    TransactionType,
)


class BalanceStore(Protocol):
    async def get_balance(self, player_id: int) -> Balance: ...

    async def add_currency(
        self,
        player_id: int,
        currency: CurrencyType,
        amount: int,
    ) -> Balance: ...

    async def remove_currency(
        self,
        player_id: int,
        currency: CurrencyType,
        amount: int,
    ) -> Balance: ...


class TransactionLog(Protocol):
    async def record(
        self,
        *,
        player_id: int,
        transaction_type: TransactionType,
        currency: CurrencyType,
        amount: int,
        balance_after: int,
        reference_id: str | None = None,
        description: str | None = None,
    ) -> Transaction: ...

    async def list_recent(
        self,
        player_id: int,
        limit: int = 20,
        offset: int = 0,
    ) -> Sequence[Transaction]: ...


class RewardStore(Protocol):
    async def claim_reward(
        self,
        player_id: int,
        reward_type: RewardType,
        today: date,
    ) -> RewardClaim: ...

    async def last_claim(
        self,
        player_id: int,
        reward_type: RewardType,
    ) -> RewardClaim | None: ...
