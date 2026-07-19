from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from larpcard.bot.container import AppContainer
from larpcard.bot.ui.marketplace_view import (
    MarketplaceBrowseView,
    MyListingsView,
    SellFlowView,
)
from larpcard.cards.domain import Rarity
from larpcard.marketplace.domain import ListingFilters, ListingSort

logger = logging.getLogger(__name__)

_SORT_CHOICES = [
    app_commands.Choice(name="Newest listings", value="newest"),
    app_commands.Choice(name="Price: low to high", value="price_asc"),
    app_commands.Choice(name="Price: high to low", value="price_desc"),
    app_commands.Choice(name="Highest rarity", value="rarity"),
]


class MarketplaceCog(commands.Cog):
    market = app_commands.Group(
        name="market",
        description="Buy and sell cards on the community marketplace.",
        guild_only=True,
    )

    def __init__(self, container: AppContainer) -> None:
        self._container = container

    @market.command(name="browse", description="Browse cards for sale.")
    @app_commands.describe(
        character="Filter by character name",
        series="Filter by series name",
        rarity="Filter by rarity",
        max_price="Only show listings at or below this price",
        seller="Only show listings from this seller",
        sort="How to order listings",
    )
    @app_commands.choices(
        rarity=[
            app_commands.Choice(name="Common", value="common"),
            app_commands.Choice(name="Legendary", value="legendary"),
        ],
        sort=_SORT_CHOICES,
    )
    async def browse(
        self,
        interaction: discord.Interaction,
        character: str | None = None,
        series: str | None = None,
        rarity: app_commands.Choice[str] | None = None,
        max_price: int | None = None,
        seller: discord.Member | None = None,
        sort: app_commands.Choice[str] | None = None,
    ) -> None:
        await interaction.response.defer(thinking=True)
        filters = ListingFilters(
            rarity=Rarity(rarity.value) if rarity else None,
            series_name=f"%{series}%" if series else None,
            character_name=f"%{character}%" if character else None,
            seller_id=seller.id if seller else None,
            max_price=max_price,
        )
        view = MarketplaceBrowseView(
            self._container,
            filters=filters,
            sort=ListingSort(sort.value) if sort else ListingSort.NEWEST,
            viewer_id=interaction.user.id,
        )
        embed, file = await view.build()
        if file is None:
            await interaction.followup.send(embed=embed, view=view)
        else:
            await interaction.followup.send(embed=embed, file=file, view=view)
        logger.info(
            "marketplace_browsed",
            extra={"viewer_id": interaction.user.id},
        )

    @market.command(name="sell", description="List a card from your inventory for sale.")
    async def sell(self, interaction: discord.Interaction) -> None:
        view = SellFlowView(self._container, interaction.user.id)
        count = await view.load_cards()
        if count == 0:
            await interaction.response.send_message(
                "You do not have any cards to sell yet. Claim some with `/drop`!",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            "Pick the card you want to list:",
            view=view,
            ephemeral=True,
        )

    @market.command(name="my-listings", description="Manage your active marketplace listings.")
    async def my_listings(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True, ephemeral=True)
        view = MyListingsView(self._container, interaction.user.id)
        embed, file = await view.build()
        if file is None:
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        else:
            await interaction.followup.send(
                embed=embed, file=file, view=view, ephemeral=True
            )
