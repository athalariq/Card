from __future__ import annotations

import logging
from datetime import date, timedelta

from larpcard.economy.domain import (
    Balance,
    CurrencyType,
    InsufficientFundsError,
    NegativeAmountError,
    RewardAlreadyClaimedError,
    RewardAvailability,
    RewardClaim,
    RewardType,
    Transaction,
    TransactionType,
)
from larpcard.economy.ports import BalanceStore, RewardStore, TransactionLog

logger = logging.getLogger(__name__)

_DAILY_REWARD_AMOUNT = 100
_WEEKLY_REWARD_AMOUNT = 500
_STREAK_BONUS_THRESHOLD = 7
_STREAK_BONUS_MULTIPLIER = 2
_WEEKLY_COOLDOWN_DAYS = 7
_WEEKLY_STREAK_GRACE_DAYS = 13
_DAILY_STREAK_GRACE_DAYS = 1


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

    @property
    def daily_reward_amount(self) -> int:
        return self._daily_reward_amount

    @property
    def weekly_reward_amount(self) -> int:
        return self._weekly_reward_amount

    @property
    def streak_bonus_threshold(self) -> int:
        return self._streak_bonus_threshold

    @property
    def streak_bonus_multiplier(self) -> int:
        return self._streak_bonus_multiplier

    def final_daily_amount(self, streak: int) -> int:
        """Coins actually credited for a daily claim at the given streak."""

        if streak > 0 and streak % self._streak_bonus_threshold == 0:
            return self._daily_reward_amount * self._streak_bonus_multiplier
        return self._daily_reward_amount

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
        except RewardAlreadyClaimedError as error:
            raise RewardAlreadyClaimedError(
                "daily reward already claimed",
                next_available=error.next_available
                or await self._next_available(player_id, RewardType.DAILY, today),
            ) from error

        amount = self.final_daily_amount(claim.streak)

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
        last = await self._rewards.last_claim(player_id, RewardType.WEEKLY)
        if last is not None:
            last_claim_date = last.claim_date or last.claimed_at.date()
            next_available = last_claim_date + timedelta(days=_WEEKLY_COOLDOWN_DAYS)
            if today < next_available:
                raise RewardAlreadyClaimedError(
                    "weekly reward already claimed",
                    next_available=next_available,
                )
        try:
            claim = await self._rewards.claim_reward(player_id, RewardType.WEEKLY, today)
        except RewardAlreadyClaimedError as error:
            raise RewardAlreadyClaimedError(
                "weekly reward already claimed",
                next_available=error.next_available
                or await self._next_available(player_id, RewardType.WEEKLY, today),
            ) from error

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

    async def last_reward_claim(
        self,
        player_id: int,
        reward_type: RewardType,
    ) -> RewardClaim | None:
        return await self._rewards.last_claim(player_id, reward_type)

    async def reward_availability(
        self,
        player_id: int,
        reward_type: RewardType,
    ) -> RewardAvailability:
        today = date.today()
        last = await self._rewards.last_claim(player_id, reward_type)
        if last is None:
            return RewardAvailability(
                reward_type=reward_type,
                streak=0,
                on_cooldown=False,
                next_available=today,
            )

        last_claim_date = last.claim_date or last.claimed_at.date()
        gap = (today - last_claim_date).days
        if reward_type is RewardType.DAILY:
            on_cooldown = gap < 1
            streak = last.streak if gap <= _DAILY_STREAK_GRACE_DAYS else 0
            next_available = last_claim_date + timedelta(days=1) if on_cooldown else today
        else:
            on_cooldown = gap < _WEEKLY_COOLDOWN_DAYS
            streak = last.streak if gap <= _WEEKLY_STREAK_GRACE_DAYS else 0
            next_available = (
                last_claim_date + timedelta(days=_WEEKLY_COOLDOWN_DAYS)
                if on_cooldown
                else today
            )
        return RewardAvailability(
            reward_type=reward_type,
            streak=streak,
            on_cooldown=on_cooldown,
            next_available=next_available,
        )

    async def _next_available(
        self,
        player_id: int,
        reward_type: RewardType,
        today: date,
    ) -> date:
        last = await self._rewards.last_claim(player_id, reward_type)
        if last is None:
            return today
        last_claim_date = last.claim_date or last.claimed_at.date()
        cooldown = (
            1 if reward_type is RewardType.DAILY else _WEEKLY_COOLDOWN_DAYS
        )
        return last_claim_date + timedelta(days=cooldown)


def _get_amount(balance: Balance, currency: CurrencyType) -> int:
    match currency:
        case CurrencyType.COINS:
            return balance.coins
        case CurrencyType.GEMS:
            return balance.gems
        case CurrencyType.EVENT_TOKENS:
            return balance.event_tokens
