from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from larpcard.bot.container import AppContainer
from larpcard.bot.ui import formatting as fmt
from larpcard.economy.domain import (
    CurrencyType,
    RewardAlreadyClaimedError,
    RewardClaim,
    RewardType,
)

logger = logging.getLogger(__name__)


class RewardsCog(commands.Cog):
    def __init__(self, container: AppContainer) -> None:
        self._container = container

    @app_commands.command(name="daily", description="Claim your daily coin reward.")
    @app_commands.guild_only()
    async def daily(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True)
        try:
            claim = await self._container.economy.claim_daily_reward(
                interaction.user.id
            )
        except RewardAlreadyClaimedError as error:
            await self._already_claimed(interaction, "daily", error)
            return

        economy = self._container.economy
        amount = economy.final_daily_amount(claim.streak)
        bonus = amount > economy.daily_reward_amount
        embed = discord.Embed(
            title=f"{fmt.GIFT} Daily reward claimed!",
            color=discord.Color.green(),
        )
        lines = [
            f"{fmt.COIN} **+{amount:,}** coins",
            f"{fmt.FIRE} Streak: **{claim.streak}** day{'s' if claim.streak != 1 else ''}",
        ]
        if bonus:
            lines.append(
                f"\u2728 {economy.streak_bonus_threshold}-day milestone: "
                f"reward x{economy.streak_bonus_multiplier}!"
            )
        else:
            days_left = economy.streak_bonus_threshold - (
                claim.streak % economy.streak_bonus_threshold
            )
            lines.append(
                f"{days_left} more day{'s' if days_left != 1 else ''} "
                "until your streak bonus doubles."
            )
        embed.description = "\n".join(lines)
        await self._send_claim(interaction, embed, claim)

    @app_commands.command(name="weekly", description="Claim your weekly gem reward.")
    @app_commands.guild_only()
    async def weekly(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True)
        try:
            claim = await self._container.economy.claim_weekly_reward(
                interaction.user.id
            )
        except RewardAlreadyClaimedError as error:
            await self._already_claimed(interaction, "weekly", error)
            return

        economy = self._container.economy
        embed = discord.Embed(
            title=f"{fmt.GEM} Weekly reward claimed!",
            description=(
                f"{fmt.GEM} **+{economy.weekly_reward_amount:,}** gems\n"
                f"{fmt.FIRE} Streak: **{claim.streak}** "
                f"week{'s' if claim.streak != 1 else ''}"
            ),
            color=discord.Color.purple(),
        )
        await self._send_claim(interaction, embed, claim)

    async def _send_claim(
        self,
        interaction: discord.Interaction,
        embed: discord.Embed,
        claim: RewardClaim,
    ) -> None:
        balance = await self._container.economy.get_balance(interaction.user.id)
        currency = (
            CurrencyType.COINS
            if claim.reward_type is RewardType.DAILY
            else CurrencyType.GEMS
        )
        icon = fmt.currency_icon(currency)
        current = balance.coins if currency is CurrencyType.COINS else balance.gems
        embed.set_footer(text=f"New balance: {icon} {current:,}")
        await interaction.followup.send(embed=embed)

    async def _already_claimed(
        self,
        interaction: discord.Interaction,
        label: str,
        error: RewardAlreadyClaimedError,
    ) -> None:
        next_available = error.next_available
        if next_available is not None:
            timestamp = fmt.discord_reset_timestamp(next_available)
            when = f"You can claim again <t:{timestamp}:R>."
        else:
            when = "Try again tomorrow."
        await interaction.followup.send(
            f"You have already claimed your **{label}** reward. {when}",
            ephemeral=True,
        )
        logger.info(
            "reward_claim_rejected",
            extra={"player_id": interaction.user.id, "reward": label},
        )
