from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from larpcard.bot.container import AppContainer
from larpcard.bot.ui.trade_view import TradeSessionView, trade_status_embed
from larpcard.trade.domain import TradeError

logger = logging.getLogger(__name__)


class TradeCog(commands.Cog):
    def __init__(self, container: AppContainer) -> None:
        self._container = container

    @app_commands.command(name="trade", description="Start a card trade with another player.")
    @app_commands.guild_only()
    @app_commands.describe(partner="The player you want to trade with")
    async def trade(
        self,
        interaction: discord.Interaction,
        partner: discord.Member,
    ) -> None:
        if partner.id == interaction.user.id:
            await interaction.response.send_message(
                "You cannot trade with yourself.",
                ephemeral=True,
            )
            return
        if partner.bot:
            await interaction.response.send_message(
                "Bots do not collect cards. Pick a human!",
                ephemeral=True,
            )
            return

        await interaction.response.defer(thinking=True)
        player1 = interaction.user
        try:
            trade = await self._container.trade.initiate(
                player1.id,
                partner.id,
            )
        except TradeError as error:
            await interaction.followup.send(
                f"Could not start the trade: {error}",
                ephemeral=True,
            )
            return

        view = TradeSessionView(
            self._container,
            trade.id,
            player1_id=player1.id,
            player2_id=partner.id,
            player1_name=player1.display_name,
            player2_name=partner.display_name,
        )
        embed = trade_status_embed(trade, player1.display_name, partner.display_name)
        message = await interaction.followup.send(
            content=(
                f"\U0001F501 {player1.mention} started a card trade with "
                f"{partner.mention}!"
            ),
            embed=embed,
            view=view,
            wait=True,
        )
        view.bind_message(message)
        logger.info(
            "trade_started",
            extra={
                "trade_id": str(trade.id),
                "player1_id": player1.id,
                "player2_id": partner.id,
            },
        )
