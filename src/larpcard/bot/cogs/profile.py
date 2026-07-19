from __future__ import annotations

import logging
from datetime import date

import discord
from discord import app_commands
from discord.ext import commands

from larpcard.bot.container import AppContainer
from larpcard.bot.ui import formatting as fmt
from larpcard.cards.domain import Rarity
from larpcard.economy.domain import RewardType
from larpcard.inventory.domain import InventoryFilters

logger = logging.getLogger(__name__)


class ProfileCog(commands.Cog):
    def __init__(self, container: AppContainer) -> None:
        self._container = container

    @app_commands.command(name="profile", description="Show a player's collection profile.")
    @app_commands.guild_only()
    @app_commands.describe(member="Player to inspect (defaults to you)")
    async def profile(
        self,
        interaction: discord.Interaction,
        member: discord.Member | None = None,
    ) -> None:
        await interaction.response.defer(thinking=True)
        target = member or interaction.user
        player_id = target.id

        economy = self._container.economy
        inventory = self._container.inventory

        balance = await economy.get_balance(player_id)
        total_page = await inventory.list_cards(player_id, page_size=1)
        legendary_page = await inventory.list_cards(
            player_id,
            filters=InventoryFilters(rarity=Rarity.LEGENDARY),
            page_size=1,
        )
        favorites_page = await inventory.list_cards(
            player_id,
            filters=InventoryFilters(favorites_only=True),
            page_size=1,
        )
        daily = await economy.reward_availability(player_id, RewardType.DAILY)
        weekly = await economy.reward_availability(player_id, RewardType.WEEKLY)
        recent = await economy.get_transactions(player_id, limit=3)

        embed = discord.Embed(
            title=target.display_name,
            color=discord.Color.blurple(),
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(
            name="\U0001F4B0 Wallet",
            value=fmt.balance_text(balance),
            inline=True,
        )
        collection_lines = [
            f"\U0001F0CF **{total_page.total_count:,}** cards",
            f"{fmt.rarity_icon(Rarity.LEGENDARY)} **{legendary_page.total_count:,}** legendary",
            f"{fmt.STAR} **{favorites_page.total_count:,}** favorites",
        ]
        if total_page.total_count:
            share = round(
                legendary_page.total_count * 100 / total_page.total_count, 1
            )
            collection_lines.append(f"\U0001F4C8 {share}% legendary rate")
        embed.add_field(
            name="\U0001F4E6 Collection",
            value="\n".join(collection_lines),
            inline=True,
        )

        rewards_lines = [
            self._reward_line("Daily", daily.streak, daily.on_cooldown, daily.next_available),
            self._reward_line("Weekly", weekly.streak, weekly.on_cooldown, weekly.next_available),
        ]
        embed.add_field(
            name=f"{fmt.GIFT} Rewards",
            value="\n".join(rewards_lines),
            inline=False,
        )

        if recent:
            embed.add_field(
                name="Recent activity",
                value="\n".join(fmt.transaction_line(t) for t in recent),
                inline=False,
            )
        embed.set_footer(text=f"Player ID: {player_id}")
        await interaction.followup.send(embed=embed)
        logger.info(
            "profile_viewed",
            extra={"viewer_id": interaction.user.id, "target_id": player_id},
        )

    def _reward_line(
        self,
        label: str,
        streak: int,
        on_cooldown: bool,
        next_available: date,
    ) -> str:
        if on_cooldown:
            timestamp = fmt.discord_reset_timestamp(next_available)
            status = f"available again <t:{timestamp}:R>"
        else:
            status = "**ready to claim!**"
        unit = "day" if label == "Daily" else "week"
        return f"{label}: {fmt.FIRE} {streak} {unit}{'s' if streak != 1 else ''} streak · {status}"
