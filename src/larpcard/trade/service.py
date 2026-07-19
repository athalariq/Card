from __future__ import annotations

import logging
from uuid import UUID, uuid4

from larpcard.trade.domain import (
    Trade,
    TradeCardNotOwnedError,
    TradeError,
    TradeInvalidStateError,
    TradeNotFoundError,
    TradeNotParticipantError,
    TradeState,
)
from larpcard.trade.ports import TradeRepository

logger = logging.getLogger(__name__)


class TradeService:
    def __init__(
        self,
        *,
        repository: TradeRepository,
    ) -> None:
        self._repository = repository

    async def initiate(
        self,
        player1_id: int,
        player2_id: int,
    ) -> Trade:
        if player1_id == player2_id:
            raise TradeError("cannot trade with yourself")

        trade = await self._repository.create(
            trade_id=uuid4(),
            player1_id=player1_id,
            player2_id=player2_id,
        )
        logger.info(
            "trade_initiated",
            extra={
                "trade_id": str(trade.id),
                "player1_id": player1_id,
                "player2_id": player2_id,
            },
        )
        return trade

    async def add_cards(
        self,
        trade_id: UUID,
        player_id: int,
        ownership_ids: list[UUID],
    ) -> Trade:
        trade = await self._repository.get(trade_id)
        if trade is None:
            raise TradeNotFoundError(trade_id)
        if player_id not in (trade.player1_id, trade.player2_id):
            raise TradeNotParticipantError(trade_id, player_id)
        if not trade.is_active:
            raise TradeInvalidStateError(
                f"trade is in state {trade.state.value} and cannot be modified"
            )

        updated = await self._repository.add_cards(
            trade_id, player_id, ownership_ids
        )
        return updated

    async def confirm(
        self,
        trade_id: UUID,
        player_id: int,
    ) -> Trade:
        trade = await self._repository.get(trade_id)
        if trade is None:
            raise TradeNotFoundError(trade_id)
        if player_id not in (trade.player1_id, trade.player2_id):
            raise TradeNotParticipantError(trade_id, player_id)
        if not trade.is_active:
            raise TradeInvalidStateError("trade is no longer active")

        new_state = self._next_state(trade.state, player_id, trade)
        await self._repository.set_state(trade_id, new_state.value)

        if new_state == TradeState.BOTH_CONFIRMED:
            await self._execute(trade_id)

        logger.info(
            "trade_confirmed",
            extra={
                "trade_id": str(trade_id),
                "player_id": player_id,
                "new_state": new_state.value,
            },
        )
        result = await self._repository.get(trade_id)
        return result  # type: ignore[return-value]

    async def cancel(
        self,
        trade_id: UUID,
        player_id: int,
    ) -> None:
        trade = await self._repository.get(trade_id)
        if trade is None:
            raise TradeNotFoundError(trade_id)
        if player_id not in (trade.player1_id, trade.player2_id):
            raise TradeNotParticipantError(trade_id, player_id)
        if not trade.is_active:
            raise TradeInvalidStateError("trade is already completed or cancelled")

        await self._repository.cancel(trade_id)
        logger.info(
            "trade_cancelled",
            extra={
                "trade_id": str(trade_id),
                "player_id": player_id,
            },
        )

    async def _execute(self, trade_id: UUID) -> None:
        trade = await self._repository.get(trade_id)
        if trade is None:
            raise TradeNotFoundError(trade_id)

        await self._repository.complete(trade_id)
        logger.info("trade_completed", extra={"trade_id": str(trade_id)})

    def _next_state(
        self,
        current: TradeState,
        confirming_player_id: int,
        trade: Trade,
    ) -> TradeState:
        match current:
            case TradeState.PENDING:
                if confirming_player_id == trade.player1_id:
                    return TradeState.PLAYER1_CONFIRMED
                return TradeState.PLAYER2_CONFIRMED
            case TradeState.PLAYER1_CONFIRMED:
                if confirming_player_id == trade.player2_id:
                    return TradeState.BOTH_CONFIRMED
                return TradeState.PLAYER1_CONFIRMED
            case TradeState.PLAYER2_CONFIRMED:
                if confirming_player_id == trade.player1_id:
                    return TradeState.BOTH_CONFIRMED
                return TradeState.PLAYER2_CONFIRMED
            case _:
                return current

    async def get_trade(self, trade_id: UUID) -> Trade:
        trade = await self._repository.get(trade_id)
        if trade is None:
            raise TradeNotFoundError(trade_id)
        return trade
