from __future__ import annotations

from typing import Protocol
from uuid import UUID

from larpcard.inventory.domain import InventoryFilters, InventoryPage, InventorySort


class InventoryQuery(Protocol):
    async def query(
        self,
        player_id: int,
        *,
        filters: InventoryFilters,
        sort: InventorySort,
        page: int = 1,
        page_size: int = 20,
    ) -> InventoryPage: ...

    async def toggle_favorite(
        self,
        player_id: int,
        ownership_id: UUID,
    ) -> bool: ...
