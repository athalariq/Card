from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from larpcard.cards.domain import Rarity, rarity_style
from larpcard.config import Settings
from larpcard.database.models import (
    CardDefinitionModel,
    CharacterModel,
    SeriesModel,
)
from larpcard.database.session import Database
from larpcard.log_setup import configure_logging

logger = logging.getLogger(__name__)


class CatalogCard(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    character: str = Field(min_length=1, max_length=160)
    series: str = Field(min_length=1, max_length=160)
    series_slug: str | None = Field(default=None, min_length=1, max_length=180)
    aliases: list[str] = Field(default_factory=list)
    image: str = Field(min_length=1)
    frame: str | None = None
    rarity: Rarity
    edition: str = Field(default="standard", min_length=1, max_length=80)
    variant: str = Field(default="base", min_length=1, max_length=80)
    tags: list[str] = Field(default_factory=list)
    release_date: date | None = None
    artist: str | None = Field(default=None, max_length=160)
    drop_weight: float | None = Field(default=None, gt=0)
    active: bool = True


CATALOG_ADAPTER = TypeAdapter(list[CatalogCard])


@dataclass(frozen=True, slots=True)
class ImportResult:
    series_created: int = 0
    characters_created: int = 0
    cards_created: int = 0
    cards_updated: int = 0


class CatalogImporter:
    def __init__(
        self,
        database: Database,
        asset_root: Path,
        *,
        require_assets: bool = True,
    ) -> None:
        self._database = database
        self._asset_root = asset_root.resolve()
        self._require_assets = require_assets

    async def import_cards(self, cards: list[CatalogCard]) -> ImportResult:
        self._validate_assets(cards)
        series_created = 0
        characters_created = 0
        cards_created = 0
        cards_updated = 0

        async with self._database.sessions() as session, session.begin():
            for entry in cards:
                series, created_series = await self._get_or_create_series(session, entry)
                character, created_character = await self._get_or_create_character(
                    session,
                    series,
                    entry,
                )
                created_card = await self._upsert_card(session, character, entry)
                series_created += int(created_series)
                characters_created += int(created_character)
                cards_created += int(created_card)
                cards_updated += int(not created_card)

        return ImportResult(
            series_created=series_created,
            characters_created=characters_created,
            cards_created=cards_created,
            cards_updated=cards_updated,
        )

    def _validate_assets(self, cards: list[CatalogCard]) -> None:
        if not self._require_assets:
            return
        for entry in cards:
            self.validate_asset_path(entry.image)
            if entry.frame:
                self.validate_asset_path(entry.frame)

    def validate_asset_path(self, relative_path: str) -> None:
        path = (self._asset_root / relative_path).resolve()
        if not path.is_relative_to(self._asset_root):
            raise ValueError(f"asset path escapes the configured root: {relative_path}")
        if not path.is_file():
            raise ValueError(f"asset does not exist: {relative_path}")

    async def _get_or_create_series(
        self,
        session: AsyncSession,
        entry: CatalogCard,
    ) -> tuple[SeriesModel, bool]:
        slug = entry.series_slug or slugify(entry.series)
        series = await session.scalar(
            select(SeriesModel).where(
                or_(SeriesModel.slug == slug, SeriesModel.name == entry.series)
            )
        )
        if series is not None:
            if series.name != entry.series or series.slug != slug:
                raise ValueError(
                    f"series identity conflict for name={entry.series!r}, slug={slug!r}"
                )
            return series, False
        series = SeriesModel(name=entry.series, slug=slug)
        session.add(series)
        await session.flush()
        return series, True

    async def _get_or_create_character(
        self,
        session: AsyncSession,
        series: SeriesModel,
        entry: CatalogCard,
    ) -> tuple[CharacterModel, bool]:
        character = await session.scalar(
            select(CharacterModel).where(
                CharacterModel.series_id == series.id,
                CharacterModel.name == entry.character,
            )
        )
        aliases = sorted(set(entry.aliases))
        if character is not None:
            character.aliases = aliases
            return character, False
        character = CharacterModel(
            series_id=series.id,
            name=entry.character,
            aliases=aliases,
        )
        session.add(character)
        await session.flush()
        return character, True

    async def _upsert_card(
        self,
        session: AsyncSession,
        character: CharacterModel,
        entry: CatalogCard,
    ) -> bool:
        definition = await session.scalar(
            select(CardDefinitionModel).where(
                CardDefinitionModel.character_id == character.id,
                CardDefinitionModel.edition == entry.edition,
                CardDefinitionModel.variant == entry.variant,
            )
        )
        created = definition is None
        if definition is None:
            definition = CardDefinitionModel(
                character_id=character.id,
                edition=entry.edition,
                variant=entry.variant,
            )
            session.add(definition)

        definition.image_path = entry.image
        definition.frame_path = entry.frame
        definition.rarity = entry.rarity
        definition.tags = sorted(set(entry.tags))
        definition.release_date = entry.release_date
        definition.artist = entry.artist
        definition.drop_weight = (
            entry.drop_weight
            if entry.drop_weight is not None
            else rarity_style(entry.rarity).default_drop_weight
        )
        definition.is_active = entry.active
        return created


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    if not slug:
        raise ValueError(f"cannot derive a series slug from {value!r}")
    return slug


def load_catalog(path: Path) -> list[CatalogCard]:
    with path.open("r", encoding="utf-8") as source:
        payload = json.load(source)
    return CATALOG_ADAPTER.validate_python(payload)


async def run_import(args: argparse.Namespace) -> ImportResult:
    settings = Settings()
    database = Database.connect(settings.database_url)
    try:
        importer = CatalogImporter(
            database,
            settings.asset_root,
            require_assets=not args.allow_missing_assets,
        )
        return await importer.import_cards(load_catalog(args.catalog))
    finally:
        await database.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import LarpCard card definitions.")
    parser.add_argument("catalog", type=Path, help="Path to a JSON array of card definitions.")
    parser.add_argument(
        "--allow-missing-assets",
        action="store_true",
        help="Import metadata before referenced artwork files are present.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    settings = Settings()
    configure_logging(settings.log_level)
    result = asyncio.run(run_import(args))
    logger.info(
        "catalog_import_completed",
        extra={
            "series_created": result.series_created,
            "characters_created": result.characters_created,
            "cards_created": result.cards_created,
            "cards_updated": result.cards_updated,
        },
    )


if __name__ == "__main__":
    main()
