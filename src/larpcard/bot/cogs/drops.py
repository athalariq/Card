from __future__ import annotations

import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands
from PIL import Image

from larpcard.bot.container import AppContainer
from larpcard.bot.ui.drop_view import DropClaimView
from larpcard.bot.ui.rendering import encode_png, render_card_image
from larpcard.drops.domain import CardPoolEmptyError, DropCooldownError, DropSlot

logger = logging.getLogger(__name__)


class DropsCog(commands.Cog):
    def __init__(self, container: AppContainer) -> None:
        self._container = container

    @app_commands.command(name="drop", description="Generate a collectible card drop.")
    @app_commands.guild_only()
    async def drop(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True)
        if interaction.channel_id is None:
            await interaction.followup.send(
                "Drops can only be created in a server channel.",
                ephemeral=True,
            )
            return
        is_admin = (
            isinstance(interaction.user, discord.Member)
            and interaction.user.guild_permissions.administrator
        )
        try:
            drop = await self._container.drops.create_drop(
                creator_id=interaction.user.id,
                guild_id=interaction.guild_id,
                channel_id=interaction.channel_id,
                skip_cooldown=is_admin,
            )
        except DropCooldownError as error:
            await interaction.followup.send(
                f"Drop cooldown: {error.retry_after_seconds} seconds remaining",
                ephemeral=True,
            )
            return
        except CardPoolEmptyError:
            logger.exception("drop_card_pool_empty")
            await interaction.followup.send(
                "The active card pool is not ready yet.",
                ephemeral=True,
            )
            return

        rendered = await asyncio.gather(*(self._render_slot(slot) for slot in drop.slots))
        sheet = await asyncio.to_thread(self._container.renderer.compose_drop, rendered)
        payload = await asyncio.to_thread(encode_png, sheet)
        view = DropClaimView(self._container.drops, drop)
        message = await interaction.followup.send(
            file=discord.File(payload, filename=f"drop-{drop.id}.png"),
            view=view,
            wait=True,
        )
        view.bind_message(message)
        try:
            await self._container.drops.bind_message(drop.id, message.id)
        except Exception:
            logger.exception(
                "drop_message_binding_failed",
                extra={"drop_id": drop.id, "message_id": message.id},
            )

    async def _render_slot(self, slot: DropSlot) -> Image.Image:
        return await render_card_image(
            self._container,
            slot.card,
            slot.image_path,
            slot.frame_path,
        )
