from __future__ import annotations

import logging
from uuid import UUID

from larpcard.inventory.domain import InventoryFilters, InventoryPage, InventorySort
from larpcard.inventory.ports import InventoryQuery

logger = logging.getLogger(__name__)

_DEFAULT_PAGE_SIZE = 20
_MAX_PAGE_SIZE = 100


class InventoryService:
    def __init__(
        self,
        *,
        query: InventoryQuery,
        default_page_size: int = _DEFAULT_PAGE_SIZE,
        max_page_size: int = _MAX_PAGE_SIZE,
    ) -> None:
        self._query = query
        self._default_page_size = default_page_size
        self._max_page_size = max_page_size

    async def list_cards(
        self,
        player_id: int,
        *,
        filters: InventoryFilters | None = None,
        sort: InventorySort = InventorySort.NEWEST,
        page: int = 1,
        page_size: int | None = None,
    ) -> InventoryPage:
        if page < 1:
            page = 1
        actual_page_size = self._default_page_size if page_size is None else page_size
        if actual_page_size < 1:
            actual_page_size = 1
        if actual_page_size > self._max_page_size:
            actual_page_size = self._max_page_size

        return await self._query.query(
            player_id,
            filters=filters or InventoryFilters(),
            sort=sort,
            page=page,
            page_size=actual_page_size,
        )

    async def toggle_favorite(
        self,
        player_id: int,
        ownership_id: UUID,
    ) -> bool:
        new_state = await self._query.toggle_favorite(player_id, ownership_id)
        logger.info(
            "favorite_toggled",
            extra={
                "player_id": player_id,
                "ownership_id": str(ownership_id),
                "is_favorite": new_state,
            },
        )
        return new_state
