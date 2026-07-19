from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from larpcard.bot.container import AppContainer
from larpcard.bot.ui.inventory_view import InventoryView
from larpcard.cards.domain import Rarity
from larpcard.inventory.domain import InventoryFilters, InventorySort

logger = logging.getLogger(__name__)


class InventoryCog(commands.Cog):
    def __init__(self, container: AppContainer) -> None:
        self._container = container

    @app_commands.command(name="inventory", description="Browse your card collection.")
    @app_commands.guild_only()
    @app_commands.describe(
        character="Filter by character name",
        series="Filter by series name",
        rarity="Filter by rarity",
        search="Free-text search across names and series",
        favorites="Only show favorited cards",
    )
    @app_commands.choices(
        rarity=[
            app_commands.Choice(name="Common", value="common"),
            app_commands.Choice(name="Legendary", value="legendary"),
        ],
    )
    async def inventory(
        self,
        interaction: discord.Interaction,
        character: str | None = None,
        series: str | None = None,
        rarity: app_commands.Choice[str] | None = None,
        search: str | None = None,
        favorites: bool = False,
    ) -> None:
        await interaction.response.defer(thinking=True)
        filters = InventoryFilters(
            series_name=f"%{series}%" if series else None,
            character_name=f"%{character}%" if character else None,
            rarity=Rarity(rarity.value) if rarity else None,
            search=search,
            favorites_only=favorites,
        )
        view = InventoryView(
            self._container,
            viewer_id=interaction.user.id,
            filters=filters,
            sort=InventorySort.NEWEST,
        )
        embed, file = await view.build()
        if file is None:
            await interaction.followup.send(embed=embed, view=view)
        else:
            await interaction.followup.send(embed=embed, file=file, view=view)
        logger.info(
            "inventory_viewed",
            extra={"viewer_id": interaction.user.id},
        )
