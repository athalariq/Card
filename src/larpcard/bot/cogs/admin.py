from __future__ import annotations

import io
import logging
import re
from pathlib import Path
from uuid import UUID

import discord
from discord import app_commands
from discord.ext import commands
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from larpcard.bot.container import AppContainer
from larpcard.cards.domain import Rarity, rarity_style
from larpcard.database.models import CardDefinitionModel, CharacterModel, SeriesModel

logger = logging.getLogger(__name__)

_ALLOWED_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".webp"})
_MAX_IMAGE_SIZE = 10 * 1024 * 1024


class AdminCog(commands.Cog):
    def __init__(self, container: AppContainer, bot: commands.Bot) -> None:
        self._container = container
        self._bot = bot

    @app_commands.command(name="card-create", description="Create a new card definition.")
    @app_commands.guild_only()
    @app_commands.describe(
        image="Card artwork image (PNG, JPG, or WebP)",
        character="Character name",
        series="Series name",
        rarity="Card rarity",
        edition="Edition label (default: standard)",
        variant="Variant label (default: base)",
        artist="Artist name (optional)",
    )
    @app_commands.choices(
        rarity=[
            app_commands.Choice(name="Common", value="common"),
            app_commands.Choice(name="Legendary", value="legendary"),
        ],
    )
    async def card_create(
        self,
        interaction: discord.Interaction,
        image: discord.Attachment,
        character: str,
        series: str,
        rarity: app_commands.Choice[str],
        edition: str = "standard",
        variant: str = "base",
        artist: str | None = None,
    ) -> None:
        if not interaction.guild:
            await interaction.response.send_message(
                "This command can only be used in a server.", ephemeral=True
            )
            return

        await interaction.response.defer(thinking=True, ephemeral=True)

        if not _is_allowed_image(image):
            await interaction.followup.send(
                "Image must be PNG, JPG, or WebP under 10 MB.", ephemeral=True
            )
            return

        if not character.strip() or not series.strip():
            await interaction.followup.send(
                "Character and series names cannot be empty.", ephemeral=True
            )
            return

        try:
            rarity_enum = Rarity(rarity.value)
        except ValueError:
            await interaction.followup.send(f"Unknown rarity: {rarity.value}", ephemeral=True)
            return

        image_data = await image.read()
        if len(image_data) > _MAX_IMAGE_SIZE:
            await interaction.followup.send("Image exceeds 10 MB limit.", ephemeral=True)
            return

        slug = _slugify(series)
        safe_name = _slugify(character)
        ext = _safe_extension(image.filename)
        filename = f"{slug}/{safe_name}.{ext}"
        relative_path = f"artwork/{filename}"
        asset_path = self._container.settings.asset_root / relative_path

        try:
            async with self._container.database.sessions() as session, session.begin():
                series_model = await _get_or_create_series(session, series, slug)
                character_model = await _get_or_create_character(
                    session, series_model.id, character
                )

                existing = await session.scalar(
                    select(CardDefinitionModel).where(
                        CardDefinitionModel.character_id == character_model.id,
                        CardDefinitionModel.edition == edition,
                        CardDefinitionModel.variant == variant,
                    )
                )
                if existing is not None:
                    await interaction.followup.send(
                        f"Card already exists for **{character}** ({edition}/{variant}).",
                        ephemeral=True,
                    )
                    return

                definition = CardDefinitionModel(
                    character_id=character_model.id,
                    image_path=relative_path,
                    rarity=rarity_enum,
                    edition=edition,
                    variant=variant,
                    artist=artist,
                )
                session.add(definition)

            asset_path.parent.mkdir(parents=True, exist_ok=True)
            img = Image.open(io.BytesIO(image_data))
            img.save(str(asset_path))

        except Exception as exc:
            logger.exception("card_create_failed")
            await interaction.followup.send(
                f"Failed to create card: {exc}", ephemeral=True
            )
            return

        await interaction.followup.send(
            f"Card created: **{character}** ({rarity_style(rarity_enum).display_name}) "
            f"from **{series}**\n`#{filename}`",
            ephemeral=True,
        )
        logger.info(
            "card_created_via_command",
            extra={
                "character": character,
                "series": series,
                "rarity": rarity_enum.value,
                "path": relative_path,
                "user_id": interaction.user.id,
            },
        )

    @app_commands.command(
        name="sync-commands",
        description="Force sync all slash commands (clears old stale commands).",
    )
    @app_commands.guild_only()
    async def sync_commands(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True, ephemeral=True)
        guild = interaction.guild
        if guild is None:
            return

        self._bot.tree.clear_commands(guild=guild)
        synced = await self._bot.tree.sync(guild=guild)
        await interaction.followup.send(
            f"Synced {len(synced)} commands to this guild. "
            "Old stale commands should be gone within a few seconds.",
            ephemeral=True,
        )
        logger.info("commands_synced_manually", extra={"count": len(synced), "guild_id": guild.id})


def _is_allowed_image(attachment: discord.Attachment) -> bool:
    ext = Path(attachment.filename).suffix.lower()
    return ext in _ALLOWED_EXTENSIONS


def _safe_extension(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext == ".jpeg":
        return "jpg"
    return ext.lstrip(".")


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-") or "unknown"


async def _get_or_create_series(
    session: AsyncSession,
    name: str,
    slug: str,
) -> SeriesModel:
    series = await session.scalar(
        select(SeriesModel).where(SeriesModel.slug == slug)
    )
    if series is not None:
        return series
    series = SeriesModel(name=name, slug=slug)
    session.add(series)
    await session.flush()
    return series


async def _get_or_create_character(
    session: AsyncSession,
    series_id: UUID,
    name: str,
) -> CharacterModel:
    character = await session.scalar(
        select(CharacterModel).where(
            CharacterModel.series_id == series_id,
            CharacterModel.name == name,
        )
    )
    if character is not None:
        return character
    character = CharacterModel(
        series_id=series_id,
        name=name,
        aliases=[],
    )
    session.add(character)
    await session.flush()
    return character
