from __future__ import annotations

import logging
from typing import cast
from uuid import UUID

import discord

from larpcard.drops.domain import (
    Drop,
    DropExpiredError,
    SlotAlreadyClaimedError,
    SlotNotFoundError,
)
from larpcard.drops.service import DropService

logger = logging.getLogger(__name__)


class ClaimButton(discord.ui.Button["DropClaimView"]):
    def __init__(self, slot_id: UUID, position: int) -> None:
        super().__init__(
            label=f"Claim {position + 1}",
            style=discord.ButtonStyle.primary,
            custom_id=f"larpcard:claim:{slot_id}",
        )
        self.slot_id = slot_id

    async def callback(self, interaction: discord.Interaction) -> None:
        view = cast(DropClaimView, self.view)
        await view.handle_claim(interaction, self)


class DropClaimView(discord.ui.View):
    def __init__(self, service: DropService, drop: Drop) -> None:
        timeout = max(1.0, (drop.expires_at - drop.created_at).total_seconds())
        super().__init__(timeout=timeout)
        self._service = service
        self._message: discord.Message | discord.WebhookMessage | None = None
        for slot in drop.slots:
            self.add_item(ClaimButton(slot.id, slot.position))

    def bind_message(self, message: discord.Message | discord.WebhookMessage) -> None:
        self._message = message

    async def handle_claim(
        self,
        interaction: discord.Interaction,
        button: ClaimButton,
    ) -> None:
        try:
            receipt = await self._service.claim(
                slot_id=button.slot_id,
                claimant_id=interaction.user.id,
            )
        except SlotAlreadyClaimedError:
            await interaction.response.send_message(
                "That card has already been claimed.",
                ephemeral=True,
            )
            return
        except DropExpiredError:
            await interaction.response.send_message(
                "This drop has expired.",
                ephemeral=True,
            )
            return
        except SlotNotFoundError:
            logger.warning("claim_slot_not_found", extra={"slot_id": button.slot_id})
            await interaction.response.send_message(
                "That card is no longer available.",
                ephemeral=True,
            )
            return

        button.disabled = True
        button.style = discord.ButtonStyle.success
        button.label = "Claimed"
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(
            f"{interaction.user.mention} used their drop powers to claim "
            f"**{receipt.character_name}**!\n\n`{receipt.claim_code}`"
        )

    async def on_timeout(self) -> None:
        for item in self.children:
            if isinstance(item, discord.ui.Button) and not item.disabled:
                item.disabled = True
                item.style = discord.ButtonStyle.secondary
        if self._message is None:
            return
        try:
            await self._message.edit(view=self)
        except discord.HTTPException:
            logger.exception("drop_timeout_message_edit_failed")
