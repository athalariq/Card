from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from larpcard.cards.domain import Rarity


class InventorySort(StrEnum):
    SERIES = "series"
    CHARACTER = "character"
    RARITY = "rarity"
    NEWEST = "newest"
    OLDEST = "oldest"
    DUPLICATES = "duplicates"
    FAVORITES = "favorites"


class InventoryGroup(StrEnum):
    NONE = "none"
    SERIES = "series"
    CHARACTER = "character"
    RARITY = "rarity"


@dataclass(frozen=True, slots=True)
class InventoryFilters:
    series_name: str | None = None
    character_name: str | None = None
    rarity: Rarity | None = None
    search: str | None = None
    favorites_only: bool = False


@dataclass(frozen=True, slots=True)
class InventoryCard:
    ownership_id: UUID
    definition_id: UUID
    print_number: int
    character_name: str
    series_name: str
    rarity: Rarity
    edition: str
    variant: str
    is_favorite: bool
    acquired_at: datetime
    image_path: str


@dataclass(frozen=True, slots=True)
class InventoryPage:
    items: tuple[InventoryCard, ...]
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
