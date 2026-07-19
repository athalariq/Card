from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from larpcard.cards.domain import Rarity


class ListingStatus(StrEnum):
    ACTIVE = "active"
    SOLD = "sold"
    CANCELLED = "cancelled"


class ListingSort(StrEnum):
    NEWEST = "newest"
    OLDEST = "oldest"
    PRICE_ASC = "price_asc"
    PRICE_DESC = "price_desc"
    RARITY = "rarity"


@dataclass(frozen=True, slots=True)
class ListingFilters:
    rarity: Rarity | None = None
    series_name: str | None = None
    character_name: str | None = None
    seller_id: int | None = None
    min_price: int | None = None
    max_price: int | None = None
    search: str | None = None


@dataclass(frozen=True, slots=True)
class Listing:
    id: UUID
    seller_id: int
    ownership_id: UUID
    definition_id: UUID
    character_name: str
    series_name: str
    rarity: Rarity
    print_number: int
    edition: str
    variant: str
    price: int
    status: ListingStatus
    created_at: datetime
    sold_at: datetime | None
    buyer_id: int | None
    image_path: str


@dataclass(frozen=True, slots=True)
class ListingPage:
    items: tuple[Listing, ...]
    total_count: int
    page: int
    page_size: int
    total_pages: int

    @property
    def has_previous(self) -> bool:
        return self.page > 1

    @property
    def has_next(self) -> bool:
        return self.page < self.total_pages


class ListingError(Exception):
    pass


class NotOwnerError(ListingError):
    def __init__(self, ownership_id: UUID) -> None:
        self.ownership_id = ownership_id
        super().__init__(f"not the owner of card {ownership_id}")


class ListingNotFoundError(ListingError):
    def __init__(self, listing_id: UUID) -> None:
        self.listing_id = listing_id
        super().__init__(f"listing not found: {listing_id}")


class SoldOutError(ListingError):
    def __init__(self, listing_id: UUID) -> None:
        self.listing_id = listing_id
        super().__init__(f"listing already sold: {listing_id}")


class CannotBuyOwnListingError(ListingError):
    pass
