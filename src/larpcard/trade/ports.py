from __future__ import annotations

from typing import Protocol
from uuid import UUID

from larpcard.trade.domain import Trade


class TradeRepository(Protocol):
    async def create(
        self,
        trade_id: UUID,
        player1_id: int,
        player2_id: int,
    ) -> Trade: ...

    async def get(self, trade_id: UUID) -> Trade | None: ...

    async def add_cards(
        self,
        trade_id: UUID,
        player_id: int,
        ownership_ids: list[UUID],
    ) -> Trade: ...

    async def set_state(
        self,
        trade_id: UUID,
        state: str,
    ) -> None: ...

    async def complete(
        self,
        trade_id: UUID,
    ) -> None: ...

    async def cancel(self, trade_id: UUID) -> None: ...
