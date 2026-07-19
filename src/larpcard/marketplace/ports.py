from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from larpcard.marketplace.domain import Listing, ListingFilters, ListingPage, ListingSort


class MarketplaceRepository(Protocol):
    async def create_listing(
        self,
        *,
        seller_id: int,
        ownership_id: UUID,
        definition_id: UUID,
        character_name: str,
        series_name: str,
        rarity: str,
        print_number: int,
        edition: str,
        variant: str,
        price: int,
        image_path: str,
        created_at: datetime,
    ) -> Listing: ...

    async def get_active_listing(self, listing_id: UUID) -> Listing | None: ...

    async def get_listing(self, listing_id: UUID) -> Listing | None: ...

    async def mark_sold(
        self,
        listing_id: UUID,
        buyer_id: int,
        sold_at: datetime,
    ) -> None: ...

    async def cancel_listing(self, listing_id: UUID) -> None: ...

    async def query(
        self,
        *,
        filters: ListingFilters,
        sort: ListingSort,
        page: int,
        page_size: int,
    ) -> ListingPage: ...

    async def count_active_by_ownership(
        self,
        ownership_id: UUID,
    ) -> int: ...
