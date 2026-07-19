from __future__ import annotations

import unittest
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

from larpcard.economy.domain import (
    Balance,
    CurrencyType,
    InsufficientFundsError,
    NegativeAmountError,
    RewardAlreadyClaimedError,
    RewardClaim,
    RewardType,
    Transaction,
    TransactionType,
)
from larpcard.economy.service import EconomyService


class MemoryBalanceStore:
    def __init__(self) -> None:
        self._balances: dict[int, Balance] = {}

    async def get_balance(self, player_id: int) -> Balance:
        return self._balances.get(player_id, Balance(coins=0, gems=0, event_tokens=0))

    async def add_currency(
        self,
        player_id: int,
        currency: CurrencyType,
        amount: int,
    ) -> Balance:
        current = self._balances.get(player_id, Balance(coins=0, gems=0, event_tokens=0))
        new = current.with_addition(currency, amount)
        self._balances[player_id] = new
        return new

    async def remove_currency(
        self,
        player_id: int,
        currency: CurrencyType,
        amount: int,
    ) -> Balance:
        current = self._balances[player_id]
        new = current.with_subtraction(currency, amount)
        self._balances[player_id] = new
        return new


class MemoryTransactionLog:
    def __init__(self) -> None:
        self._transactions: list[Transaction] = []

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
    ) -> Transaction:
        txn = Transaction(
            id=uuid4(),
            player_id=player_id,
            transaction_type=transaction_type,
            currency=currency,
            amount=amount,
            balance_after=balance_after,
            reference_id=reference_id,
            description=description,
            created_at=datetime.now(UTC),
        )
        self._transactions.append(txn)
        return txn

    async def list_recent(
        self,
        player_id: int,
        limit: int = 20,
        offset: int = 0,
    ) -> Sequence[Transaction]:
        filtered = [t for t in self._transactions if t.player_id == player_id]
        filtered.sort(key=lambda t: t.created_at, reverse=True)
        return filtered[offset : offset + limit]


class MemoryRewardStore:
    def __init__(self) -> None:
        self._claims: list[RewardClaim] = []

    async def claim_reward(
        self,
        player_id: int,
        reward_type: RewardType,
        today: date,
    ) -> RewardClaim:
        for claim in self._claims:
            if (
                claim.player_id == player_id
                and claim.reward_type == reward_type
                and claim.claimed_at.date() == today
            ):
                raise RewardAlreadyClaimedError("already claimed")
        last_streak = 0
        for claim in reversed(self._claims):
            if claim.player_id == player_id and claim.reward_type == reward_type:
                last_streak = claim.streak
                break
        yesterday = today - timedelta(days=1)
        streak = last_streak + 1
        # reset streak if yesterday was missed
        has_yesterday = any(
            c.claimed_at.date() == yesterday
            for c in self._claims
            if c.player_id == player_id and c.reward_type == reward_type
        )
        if not has_yesterday and last_streak > 0:
            streak = 1

        claim = RewardClaim(
            id=uuid4(),
            player_id=player_id,
            reward_type=reward_type,
            currency=CurrencyType.COINS,
            amount=100,
            streak=streak,
            claimed_at=datetime.now(UTC),
        )
        self._claims.append(claim)
        return claim

    async def last_claim(
        self,
        player_id: int,
        reward_type: RewardType,
    ) -> RewardClaim | None:
        matching = [
            c for c in self._claims if c.player_id == player_id and c.reward_type == reward_type
        ]
        if not matching:
            return None
        return max(matching, key=lambda c: c.claimed_at)


class EconomyServiceTests(unittest.IsolatedAsyncioTestCase):
    def make_service(
        self,
    ) -> tuple[EconomyService, MemoryBalanceStore, MemoryTransactionLog, MemoryRewardStore]:
        balances = MemoryBalanceStore()
        transactions = MemoryTransactionLog()
        rewards = MemoryRewardStore()
        service = EconomyService(
            balances=balances,
            transactions=transactions,
            rewards=rewards,
        )
        return service, balances, transactions, rewards

    async def test_get_balance_returns_zero_for_new_player(self) -> None:
        service, _, _, _ = self.make_service()
        balance = await service.get_balance(100)
        self.assertEqual(balance, Balance(0, 0, 0))

    async def test_add_currency_increases_balance(self) -> None:
        service, _, _, _ = self.make_service()
        balance = await service.add_currency(100, CurrencyType.COINS, 500)
        self.assertEqual(balance.coins, 500)

    async def test_add_currency_records_transaction(self) -> None:
        service, _, txns, _ = self.make_service()
        await service.add_currency(100, CurrencyType.COINS, 500)
        recent = await txns.list_recent(100)
        self.assertEqual(len(recent), 1)
        self.assertEqual(recent[0].amount, 500)
        self.assertEqual(recent[0].transaction_type, TransactionType.ADMIN_GRANT)

    async def test_add_negative_amount_raises_error(self) -> None:
        service, _, _, _ = self.make_service()
        with self.assertRaises(NegativeAmountError):
            await service.add_currency(100, CurrencyType.COINS, -50)

    async def test_remove_currency_decreases_balance(self) -> None:
        service, _, _, _ = self.make_service()
        await service.add_currency(100, CurrencyType.COINS, 1000)
        balance = await service.remove_currency(100, CurrencyType.COINS, 300)
        self.assertEqual(balance.coins, 700)

    async def test_remove_insufficient_funds_raises_error(self) -> None:
        service, _, _, _ = self.make_service()
        await service.add_currency(100, CurrencyType.COINS, 100)
        with self.assertRaises(InsufficientFundsError):
            await service.remove_currency(100, CurrencyType.COINS, 200)

    async def test_transfer_moves_currency_between_players(self) -> None:
        service, _, _, _ = self.make_service()
        await service.add_currency(100, CurrencyType.COINS, 500)
        await service.transfer(100, 200, CurrencyType.COINS, 200)

        balance_100 = await service.get_balance(100)
        balance_200 = await service.get_balance(200)
        self.assertEqual(balance_100.coins, 300)
        self.assertEqual(balance_200.coins, 200)

    async def test_daily_reward_increases_coins(self) -> None:
        service, _, _, _ = self.make_service()
        claim = await service.claim_daily_reward(100)
        self.assertGreater(claim.streak, 0)
        balance = await service.get_balance(100)
        self.assertGreater(balance.coins, 0)

    async def test_daily_reward_cannot_be_claimed_twice(self) -> None:
        service, _, _, _ = self.make_service()
        await service.claim_daily_reward(100)
        with self.assertRaises(RewardAlreadyClaimedError):
            await service.claim_daily_reward(100)

    async def test_weekly_reward_increases_gems(self) -> None:
        service, _, _, _ = self.make_service()
        claim = await service.claim_weekly_reward(100)
        self.assertGreater(claim.streak, 0)
        balance = await service.get_balance(100)
        self.assertGreater(balance.gems, 0)

    async def test_weekly_reward_gated_to_seven_days(self) -> None:
        service, _, _, _ = self.make_service()
        await service.claim_weekly_reward(100)
        with self.assertRaises(RewardAlreadyClaimedError) as ctx:
            await service.claim_weekly_reward(100)
        self.assertEqual(
            ctx.exception.next_available,
            date.today() + timedelta(days=7),
        )

    async def test_weekly_reward_claimable_after_cooldown(self) -> None:
        service, _, _, rewards = self.make_service()
        old_claim = RewardClaim(
            id=uuid4(),
            player_id=100,
            reward_type=RewardType.WEEKLY,
            currency=CurrencyType.GEMS,
            amount=500,
            streak=3,
            claimed_at=datetime.now(UTC) - timedelta(days=8),
        )
        rewards._claims.append(old_claim)  # type: ignore[attr-defined]
        claim = await service.claim_weekly_reward(100)
        self.assertEqual(claim.streak, 1)  # long gap resets the streak

    async def test_daily_claim_error_carries_next_available(self) -> None:
        service, _, _, _ = self.make_service()
        await service.claim_daily_reward(100)
        with self.assertRaises(RewardAlreadyClaimedError) as ctx:
            await service.claim_daily_reward(100)
        self.assertEqual(
            ctx.exception.next_available,
            date.today() + timedelta(days=1),
        )

    async def test_reward_availability_for_new_player(self) -> None:
        service, _, _, _ = self.make_service()
        daily = await service.reward_availability(100, RewardType.DAILY)
        self.assertEqual(daily.streak, 0)
        self.assertFalse(daily.on_cooldown)
        self.assertEqual(daily.next_available, date.today())

    async def test_reward_availability_after_daily_claim(self) -> None:
        service, _, _, _ = self.make_service()
        await service.claim_daily_reward(100)
        daily = await service.reward_availability(100, RewardType.DAILY)
        self.assertEqual(daily.streak, 1)
        self.assertTrue(daily.on_cooldown)
        self.assertEqual(daily.next_available, date.today() + timedelta(days=1))

    async def test_reward_availability_resets_broken_streak(self) -> None:
        service, _, _, rewards = self.make_service()
        rewards._claims.append(  # type: ignore[attr-defined]
            RewardClaim(
                id=uuid4(),
                player_id=100,
                reward_type=RewardType.DAILY,
                currency=CurrencyType.COINS,
                amount=100,
                streak=5,
                claimed_at=datetime.now(UTC) - timedelta(days=3),
            )
        )
        daily = await service.reward_availability(100, RewardType.DAILY)
        self.assertEqual(daily.streak, 0)
        self.assertFalse(daily.on_cooldown)

    async def test_reward_availability_keeps_yesterday_streak(self) -> None:
        service, _, _, rewards = self.make_service()
        rewards._claims.append(  # type: ignore[attr-defined]
            RewardClaim(
                id=uuid4(),
                player_id=100,
                reward_type=RewardType.DAILY,
                currency=CurrencyType.COINS,
                amount=100,
                streak=4,
                claimed_at=datetime.now(UTC) - timedelta(days=1),
            )
        )
        daily = await service.reward_availability(100, RewardType.DAILY)
        self.assertEqual(daily.streak, 4)
        self.assertFalse(daily.on_cooldown)

    async def test_last_reward_claim_returns_none_when_never_claimed(self) -> None:
        service, _, _, _ = self.make_service()
        self.assertIsNone(await service.last_reward_claim(100, RewardType.DAILY))

    async def test_final_daily_amount(self) -> None:
        service, _, _, _ = self.make_service()
        self.assertEqual(service.final_daily_amount(1), 100)
        self.assertEqual(service.final_daily_amount(6), 100)
        self.assertEqual(service.final_daily_amount(7), 200)
        self.assertEqual(service.final_daily_amount(14), 200)

    async def test_reward_amounts_exposed(self) -> None:
        service, _, _, _ = self.make_service()
        self.assertEqual(service.daily_reward_amount, 100)
        self.assertEqual(service.weekly_reward_amount, 500)
        self.assertEqual(service.streak_bonus_threshold, 7)
        self.assertEqual(service.streak_bonus_multiplier, 2)

    async def test_balance_has_at_least(self) -> None:
        balance = Balance(coins=100, gems=50, event_tokens=10)
        self.assertTrue(balance.has_at_least(CurrencyType.COINS, 100))
        self.assertTrue(balance.has_at_least(CurrencyType.COINS, 50))
        self.assertFalse(balance.has_at_least(CurrencyType.COINS, 101))
        self.assertTrue(balance.has_at_least(CurrencyType.GEMS, 50))
        self.assertFalse(balance.has_at_least(CurrencyType.GEMS, 51))
        self.assertTrue(balance.has_at_least(CurrencyType.EVENT_TOKENS, 10))

    async def test_balance_with_addition(self) -> None:
        balance = Balance(coins=100, gems=50, event_tokens=10)
        new = balance.with_addition(CurrencyType.COINS, 50)
        self.assertEqual(new.coins, 150)
        self.assertEqual(new.gems, 50)
        self.assertEqual(new.event_tokens, 10)

    async def test_balance_with_subtraction(self) -> None:
        balance = Balance(coins=100, gems=50, event_tokens=10)
        new = balance.with_subtraction(CurrencyType.COINS, 30)
        self.assertEqual(new.coins, 70)
        self.assertEqual(new.gems, 50)
        self.assertEqual(new.event_tokens, 10)
