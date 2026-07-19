from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from uuid import UUID


class Rarity(StrEnum):
    COMMON = "common"
    LEGENDARY = "legendary"


@dataclass(frozen=True, slots=True)
class RarityStyle:
    display_name: str
    stars: int
    accent_rgb: tuple[int, int, int]
    highlight_rgb: tuple[int, int, int]
    default_drop_weight: float


RARITY_STYLES: dict[Rarity, RarityStyle] = {
    Rarity.COMMON: RarityStyle(
        display_name="Common",
        stars=1,
        accent_rgb=(48, 142, 255),
        highlight_rgb=(153, 213, 255),
        default_drop_weight=100.0,
    ),
    Rarity.LEGENDARY: RarityStyle(
        display_name="Legendary",
        stars=5,
        accent_rgb=(235, 47, 71),
        highlight_rgb=(255, 191, 98),
        default_drop_weight=2.0,
    ),
}


def rarity_style(rarity: Rarity) -> RarityStyle:
    """Return visual and tuning metadata without relying on rendered text."""

    return RARITY_STYLES[rarity]


@dataclass(frozen=True, slots=True)
class CardTemplate:
    id: UUID
    character_name: str
    series_name: str
    aliases: tuple[str, ...]
    image_path: str
    frame_path: str | None
    rarity: Rarity
    edition: str
    variant: str
    tags: tuple[str, ...] = field(default_factory=tuple)
    release_date: date | None = None
    artist: str | None = None
    drop_weight: float = 1.0

    def __post_init__(self) -> None:
        if not self.character_name.strip():
            raise ValueError("character_name cannot be empty")
        if not self.series_name.strip():
            raise ValueError("series_name cannot be empty")
        if self.drop_weight <= 0:
            raise ValueError("drop_weight must be positive")


@dataclass(frozen=True, slots=True)
class RenderCard:
    template_id: UUID
    character_name: str
    series_name: str
    rarity: Rarity
    print_number: int
    edition: str
    variant: str

    def __post_init__(self) -> None:
        if self.print_number < 1:
            raise ValueError("print_number must be positive")
