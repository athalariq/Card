"""Shared helpers that turn card data into Discord-ready rendered images.

The renderer is CPU-bound Pillow work, so every helper offloads to a thread
and falls back to generated placeholder artwork when files are missing.
"""

from __future__ import annotations

import asyncio
import io
import logging
from pathlib import Path
from uuid import UUID

import discord
from PIL import Image

from larpcard.bot.container import AppContainer
from larpcard.cards.assets import ArtworkNotFoundError
from larpcard.cards.domain import Rarity, RenderCard, rarity_style
from larpcard.inventory.domain import InventoryCard
from larpcard.marketplace.domain import Listing
from larpcard.trade.domain import TradeCard

logger = logging.getLogger(__name__)


async def render_card_image(
    container: AppContainer,
    card: RenderCard,
    image_path: str,
    frame_path: str | None = None,
) -> Image.Image:
    """Render one card, falling back to placeholder art when files are missing."""

    style = rarity_style(card.rarity)
    try:
        artwork = await container.artwork.load(image_path)
    except ArtworkNotFoundError:
        logger.warning(
            "card_artwork_missing",
            extra={"template_id": str(card.template_id), "path": image_path},
        )
        artwork = await asyncio.to_thread(
            container.renderer.placeholder_artwork,
            card.character_name,
            style.accent_rgb,
        )

    frame_name: str | None = None
    custom_frame: Image.Image | None = None
    if frame_path:
        frame_name = Path(frame_path).stem
        try:
            custom_frame = await container.artwork.load(frame_path)
        except ArtworkNotFoundError:
            logger.warning(
                "card_frame_missing",
                extra={"template_id": str(card.template_id), "path": frame_path},
            )
    return await asyncio.to_thread(
        container.renderer.render,
        card,
        artwork,
        custom_frame,
        frame_name,
    )


def encode_png(image: Image.Image) -> io.BytesIO:
    buffer = io.BytesIO()
    image.save(buffer, "PNG", optimize=True)
    buffer.seek(0)
    return buffer


def card_attachment(image: Image.Image, name: str) -> discord.File:
    return discord.File(encode_png(image), filename=f"{name}.png")


def _render_card(
    *,
    template_id: UUID,
    character_name: str,
    series_name: str,
    rarity: Rarity,
    print_number: int,
    edition: str,
    variant: str,
) -> RenderCard:
    return RenderCard(
        template_id=template_id,
        character_name=character_name,
        series_name=series_name,
        rarity=rarity,
        print_number=print_number,
        edition=edition,
        variant=variant,
    )


async def render_inventory_card(
    container: AppContainer,
    card: InventoryCard,
) -> Image.Image:
    return await render_card_image(
        container,
        _render_card(
            template_id=card.definition_id,
            character_name=card.character_name,
            series_name=card.series_name,
            rarity=card.rarity,
            print_number=card.print_number,
            edition=card.edition,
            variant=card.variant,
        ),
        card.image_path,
        card.frame_path,
    )


async def render_listing_card(
    container: AppContainer,
    listing: Listing,
) -> Image.Image:
    return await render_card_image(
        container,
        _render_card(
            template_id=listing.definition_id,
            character_name=listing.character_name,
            series_name=listing.series_name,
            rarity=listing.rarity,
            print_number=listing.print_number,
            edition=listing.edition,
            variant=listing.variant,
        ),
        listing.image_path,
        listing.frame_path,
    )


async def render_trade_card(
    container: AppContainer,
    card: TradeCard,
) -> Image.Image:
    return await render_card_image(
        container,
        _render_card(
            template_id=card.definition_id,
            character_name=card.character_name,
            series_name=card.series_name,
            rarity=card.rarity,
            print_number=card.print_number,
            edition=card.edition,
            variant=card.variant,
        ),
        card.image_path,
    )


def compose_trade_sheet(
    container: AppContainer,
    player1_cards: list[Image.Image],
    player2_cards: list[Image.Image],
) -> Image.Image | None:
    """Lay out both sides of a trade offer side by side."""

    renderer = container.renderer
    sheets: list[Image.Image] = []
    for cards in (player1_cards, player2_cards):
        if cards:
            sheets.append(renderer.compose_drop(cards))
    if not sheets:
        return None

    if len(sheets) == 1:
        width = sheets[0].width + 20
        height = sheets[0].height + 10
        combined = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        combined.alpha_composite(sheets[0], (10, 5))
        return combined

    gap = 24
    height = max(sheet.height for sheet in sheets)
    width = sheets[0].width + gap + sheets[1].width
    combined = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    combined.alpha_composite(sheets[0], (0, 0))
    combined.alpha_composite(sheets[1], (sheets[0].width + gap, 0))
    return combined
