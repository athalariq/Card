from __future__ import annotations

import unittest
from datetime import UTC, datetime
from uuid import UUID, uuid4

from larpcard.trade.domain import (
    Trade,
    TradeCard,
    TradeCardNotOwnedError,
    TradeError,
    TradeInvalidStateError,
    TradeNotFoundError,
    TradeNotParticipantError,
    TradeState,
)
from larpcard.trade.service import TradeService


class MemoryTradeRepository:
    def __init__(self) -> None:
        self._trades: dict[UUID, dict] = {}

    async def create(
        self,
        trade_id: UUID,
        player1_id: int,
        player2_id: int,
    ) -> Trade:
        now = datetime.now(UTC)
        trade = Trade(
            id=trade_id,
            player1_id=player1_id,
            player2_id=player2_id,
            state=TradeState.PENDING,
            player1_cards=(),
            player2_cards=(),
            created_at=now,
            completed_at=None,
        )
        self._trades[trade_id] = trade
        return trade

    async def get(self, trade_id: UUID) -> Trade | None:
        return self._trades.get(trade_id)

    async def add_cards(
        self,
        trade_id: UUID,
        player_id: int,
        ownership_ids: list[UUID],
    ) -> Trade:
        trade = self._trades.get(trade_id)
        if trade is None:
            raise TradeNotFoundError(trade_id)

        # Verify all cards are owned (simulated)
        player_cards = {}  # player_id -> cards
        if not hasattr(self, "_owned"):
            self._owned = {}  # type: ignore[attribute-defined-outside-init]
        owned = self._owned.get(player_id, set())  # type: ignore[attr-defined]
        for oid in ownership_ids:
            if oid not in owned:
                raise TradeCardNotOwnedError(f"card not owned: {oid}")

        cards = tuple(
            TradeCard(
                ownership_id=oid,
                definition_id=uuid4(),
                character_name=f"Char {oid.int & 0xFFFF}",
                series_name="Series",
                rarity="common",
                print_number=1,
                edition="standard",
                variant="base",
                image_path="artwork/card.png",
            )
            for oid in ownership_ids
        )

        if player_id == trade.player1_id:
            new_p1 = cards
            new_p2 = trade.player2_cards
        else:
            new_p1 = trade.player1_cards
            new_p2 = cards

        updated = Trade(
            id=trade.id,
            player1_id=trade.player1_id,
            player2_id=trade.player2_id,
            state=TradeState.PENDING,
            player1_cards=new_p1,
            player2_cards=new_p2,
            created_at=trade.created_at,
            completed_at=trade.completed_at,
        )
        self._trades[trade_id] = updated
        return updated

    async def set_state(
        self,
        trade_id: UUID,
        state: str,
    ) -> None:
        trade = self._trades.get(trade_id)
        if trade is not None:
            updated = Trade(
                id=trade.id,
                player1_id=trade.player1_id,
                player2_id=trade.player2_id,
                state=TradeState(state),
                player1_cards=trade.player1_cards,
                player2_cards=trade.player2_cards,
                created_at=trade.created_at,
                completed_at=trade.completed_at,
            )
            self._trades[trade_id] = updated

    async def complete(self, trade_id: UUID) -> None:
        trade = self._trades.get(trade_id)
        if trade is not None:
            updated = Trade(
                id=trade.id,
                player1_id=trade.player1_id,
                player2_id=trade.player2_id,
                state=TradeState.COMPLETED,
                player1_cards=trade.player1_cards,
                player2_cards=trade.player2_cards,
                created_at=trade.created_at,
                completed_at=datetime.now(UTC),
            )
            self._trades[trade_id] = updated

    async def cancel(self, trade_id: UUID) -> None:
        trade = self._trades.get(trade_id)
        if trade is not None:
            updated = Trade(
                id=trade.id,
                player1_id=trade.player1_id,
                player2_id=trade.player2_id,
                state=TradeState.CANCELLED,
                player1_cards=trade.player1_cards,
                player2_cards=trade.player2_cards,
                created_at=trade.created_at,
                completed_at=trade.completed_at,
            )
            self._trades[trade_id] = updated


def make_service() -> tuple[TradeService, MemoryTradeRepository]:
    repo = MemoryTradeRepository()
    service = TradeService(repository=repo)
    return service, repo


class TradeServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_initiate_creates_pending_trade(self) -> None:
        service, _ = make_service()
        trade = await service.initiate(player1_id=100, player2_id=200)
        self.assertEqual(trade.player1_id, 100)
        self.assertEqual(trade.player2_id, 200)
        self.assertEqual(trade.state, TradeState.PENDING)
        self.assertTrue(trade.is_active)

    async def test_initiate_self_trade_raises_error(self) -> None:
        service, _ = make_service()
        with self.assertRaises(TradeError):
            await service.initiate(player1_id=100, player2_id=100)

    async def test_add_cards_to_trade(self) -> None:
        service, repo = make_service()
        trade = await service.initiate(player1_id=100, player2_id=200)

        # Simulate owned cards
        oid1, oid2 = uuid4(), uuid4()
        repo._owned = {100: {oid1, oid2}}  # type: ignore[attr-defined]

        updated = await service.add_cards(trade.id, 100, [oid1, oid2])
        self.assertEqual(len(updated.player1_cards), 2)
        self.assertEqual(len(updated.player2_cards), 0)

    async def test_add_cards_not_owned_raises_error(self) -> None:
        service, repo = make_service()
        trade = await service.initiate(player1_id=100, player2_id=200)

        repo._owned = {100: set()}  # type: ignore[attr-defined]

        with self.assertRaises(TradeCardNotOwnedError):
            await service.add_cards(trade.id, 100, [uuid4()])

    async def test_add_cards_non_participant_raises_error(self) -> None:
        service, _ = make_service()
        trade = await service.initiate(player1_id=100, player2_id=200)

        with self.assertRaises(TradeNotParticipantError):
            await service.add_cards(trade.id, 300, [uuid4()])

    async def test_both_players_confirm_executes_trade(self) -> None:
        service, repo = make_service()
        trade = await service.initiate(player1_id=100, player2_id=200)

        repo._owned = {100: {uuid4()}, 200: {uuid4()}}  # type: ignore[attr-defined]
        await service.add_cards(trade.id, 100, [list(repo._owned[100])[0]])  # type: ignore[attr-defined]
        await service.add_cards(trade.id, 200, [list(repo._owned[200])[0]])  # type: ignore[attr-defined]

        await service.confirm(trade.id, 100)
        t1 = await service.get_trade(trade.id)
        self.assertEqual(t1.state, TradeState.PLAYER1_CONFIRMED)

        result = await service.confirm(trade.id, 200)
        self.assertEqual(result.state, TradeState.COMPLETED)

    async def test_cancel_by_either_player(self) -> None:
        service, _ = make_service()
        trade = await service.initiate(player1_id=100, player2_id=200)

        await service.cancel(trade.id, 100)
        t = await service.get_trade(trade.id)
        self.assertEqual(t.state, TradeState.CANCELLED)
        self.assertFalse(t.is_active)

    async def test_cancel_by_non_participant_raises_error(self) -> None:
        service, _ = make_service()
        trade = await service.initiate(player1_id=100, player2_id=200)

        with self.assertRaises(TradeNotParticipantError):
            await service.cancel(trade.id, 300)

    async def test_confirm_non_participant_raises_error(self) -> None:
        service, _ = make_service()
        trade = await service.initiate(player1_id=100, player2_id=200)

        with self.assertRaises(TradeNotParticipantError):
            await service.confirm(trade.id, 300)

    async def test_get_trade_returns_trade(self) -> None:
        service, _ = make_service()
        trade = await service.initiate(player1_id=100, player2_id=200)

        fetched = await service.get_trade(trade.id)
        self.assertEqual(fetched.id, trade.id)
        self.assertEqual(fetched.player1_id, 100)

    async def test_get_nonexistent_trade_raises_error(self) -> None:
        service, _ = make_service()
        with self.assertRaises(TradeNotFoundError):
            await service.get_trade(uuid4())

    async def test_completed_trade_cannot_be_modified(self) -> None:
        service, repo = make_service()
        trade = await service.initiate(player1_id=100, player2_id=200)
        repo._owned = {100: {uuid4()}, 200: {uuid4()}}  # type: ignore[attr-defined]

        await service.add_cards(trade.id, 100, [list(repo._owned[100])[0]])  # type: ignore[attr-defined]
        await service.confirm(trade.id, 100)
        await service.confirm(trade.id, 200)

        t = await service.get_trade(trade.id)
        self.assertEqual(t.state, TradeState.COMPLETED)

        with self.assertRaises(TradeInvalidStateError):
            await service.add_cards(trade.id, 100, [list(repo._owned[100])[0]])  # type: ignore[attr-defined]
