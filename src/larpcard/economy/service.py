from __future__ import annotations

import logging
from datetime import UTC, date, datetime

from larpcard.economy.domain import (
    Balance,
    CurrencyType,
    EconomyError,
    InsufficientFundsError,
    NegativeAmountError,
    RewardAlreadyClaimedError,
    RewardClaim,
    RewardType,
    TransactionType,
)
from larpcard.economy.ports import BalanceStore, RewardStore, TransactionLog

logger = logging.getLogger(__name__)

_DAILY_REWARD_AMOUNT = 100
_WEEKLY_REWARD_AMOUNT = 500
_STREAK_BONUS_THRESHOLD = 7
_STREAK_BONUS_MULTIPLIER = 2


class EconomyService:
    def __init__(
        self,
        *,
        balances: BalanceStore,
        transactions: TransactionLog,
        rewards: RewardStore,
        daily_reward_amount: int = _DAILY_REWARD_AMOUNT,
        weekly_reward_amount: int = _WEEKLY_REWARD_AMOUNT,
        streak_bonus_threshold: int = _STREAK_BONUS_THRESHOLD,
        streak_bonus_multiplier: int = _STREAK_BONUS_MULTIPLIER,
    ) -> None:
        self._balances = balances
        self._transactions = transactions
        self._rewards = rewards
        self._daily_reward_amount = daily_reward_amount
        self._weekly_reward_amount = weekly_reward_amount
        self._streak_bonus_threshold = streak_bonus_threshold
        self._streak_bonus_multiplier = streak_bonus_multiplier

    async def get_balance(self, player_id: int) -> Balance:
        return await self._balances.get_balance(player_id)

    async def add_currency(
        self,
        player_id: int,
        currency: CurrencyType,
        amount: int,
        *,
        transaction_type: TransactionType = TransactionType.ADMIN_GRANT,
        reference_id: str | None = None,
        description: str | None = None,
    ) -> Balance:
        if amount <= 0:
            raise NegativeAmountError("amount must be positive")
        balance = await self._balances.add_currency(player_id, currency, amount)
        await self._transactions.record(
            player_id=player_id,
            transaction_type=transaction_type,
            currency=currency,
            amount=amount,
            balance_after=_get_amount(balance, currency),
            reference_id=reference_id,
            description=description,
        )
        logger.info(
            "currency_added",
            extra={
                "player_id": player_id,
                "currency": currency.value,
                "amount": amount,
                "type": transaction_type.value,
            },
        )
        return balance

    async def remove_currency(
        self,
        player_id: int,
        currency: CurrencyType,
        amount: int,
        *,
        transaction_type: TransactionType = TransactionType.ADMIN_REMOVE,
        reference_id: str | None = None,
        description: str | None = None,
    ) -> Balance:
        if amount <= 0:
            raise NegativeAmountError("amount must be positive")
        balance = await self._balances.get_balance(player_id)
        if not balance.has_at_least(currency, amount):
            raise InsufficientFundsError(
                currency,
                amount,
                _get_amount(balance, currency),
            )
        balance = await self._balances.remove_currency(player_id, currency, amount)
        await self._transactions.record(
            player_id=player_id,
            transaction_type=transaction_type,
            currency=currency,
            amount=-amount,
            balance_after=_get_amount(balance, currency),
            reference_id=reference_id,
            description=description,
        )
        logger.info(
            "currency_removed",
            extra={
                "player_id": player_id,
                "currency": currency.value,
                "amount": amount,
                "type": transaction_type.value,
            },
        )
        return balance

    async def transfer(
        self,
        from_player_id: int,
        to_player_id: int,
        currency: CurrencyType,
        amount: int,
        *,
        transaction_type: TransactionType = TransactionType.TRADE,
        reference_id: str | None = None,
        description: str | None = None,
    ) -> Balance:
        await self.remove_currency(
            from_player_id,
            currency,
            amount,
            transaction_type=transaction_type,
            reference_id=reference_id,
            description=description,
        )
        return await self.add_currency(
            to_player_id,
            currency,
            amount,
            transaction_type=transaction_type,
            reference_id=reference_id,
            description=description,
        )

    async def claim_daily_reward(self, player_id: int) -> RewardClaim:
        today = date.today()
        try:
            claim = await self._rewards.claim_reward(player_id, RewardType.DAILY, today)
        except RewardAlreadyClaimedError:
            raise

        amount = self._daily_reward_amount
        if claim.streak > 0 and claim.streak % self._streak_bonus_threshold == 0:
            amount *= self._streak_bonus_multiplier

        await self._balances.add_currency(player_id, CurrencyType.COINS, amount)
        await self._transactions.record(
            player_id=player_id,
            transaction_type=TransactionType.DAILY_REWARD,
            currency=CurrencyType.COINS,
            amount=amount,
            balance_after=_get_amount(
                await self._balances.get_balance(player_id),
                CurrencyType.COINS,
            ),
            description=f"daily reward (streak: {claim.streak})",
        )
        logger.info(
            "daily_reward_claimed",
            extra={
                "player_id": player_id,
                "amount": amount,
                "streak": claim.streak,
            },
        )
        return claim

    async def claim_weekly_reward(self, player_id: int) -> RewardClaim:
        today = date.today()
        try:
            claim = await self._rewards.claim_reward(player_id, RewardType.WEEKLY, today)
        except RewardAlreadyClaimedError:
            raise

        amount = self._weekly_reward_amount
        await self._balances.add_currency(player_id, CurrencyType.GEMS, amount)
        await self._transactions.record(
            player_id=player_id,
            transaction_type=TransactionType.WEEKLY_REWARD,
            currency=CurrencyType.GEMS,
            amount=amount,
            balance_after=_get_amount(
                await self._balances.get_balance(player_id),
                CurrencyType.GEMS,
            ),
            description=f"weekly reward (streak: {claim.streak})",
        )
        logger.info(
            "weekly_reward_claimed",
            extra={
                "player_id": player_id,
                "amount": amount,
                "streak": claim.streak,
            },
        )
        return claim

    async def get_transactions(
        self,
        player_id: int,
        limit: int = 20,
        offset: int = 0,
    ) -> list[Transaction]:
        return list(await self._transactions.list_recent(player_id, limit, offset))


def _get_amount(balance: Balance, currency: CurrencyType) -> int:
    match currency:
        case CurrencyType.COINS:
            return balance.coins
        case CurrencyType.GEMS:
            return balance.gems
        case CurrencyType.EVENT_TOKENS:
            return balance.event_tokens
