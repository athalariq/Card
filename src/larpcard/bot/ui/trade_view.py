from __future__ import annotations

import asyncio
import logging
from uuid import UUID

import discord

from larpcard.bot.container import AppContainer
from larpcard.bot.ui import formatting as fmt
from larpcard.bot.ui.rendering import (
    card_attachment,
    compose_trade_sheet,
    render_trade_card,
)
from larpcard.inventory.domain import InventorySort
from larpcard.trade.domain import (
    Trade,
    TradeCard,
    TradeCardNotOwnedError,
    TradeInvalidStateError,
    TradeNotFoundError,
    TradeNotParticipantError,
    TradeState,
)

logger = logging.getLogger(__name__)

MAX_OFFER_CARDS = 4


def trade_status_embed(
    trade: Trade,
    player1_name: str,
    player2_name: str,
) -> discord.Embed:
    completed = trade.state is TradeState.COMPLETED
    cancelled = trade.state is TradeState.CANCELLED
    color = discord.Color.blurple()
    if completed:
        color = discord.Color.green()
    elif cancelled:
        color = discord.Color.red()

    embed = discord.Embed(
        title="\U0001F501 Card Trade",
        description=f"**{player1_name}** \u27F7 **{player2_name}**",
        color=color,
    )
    p1_marker = _confirm_marker(trade, trade.player1_id)
    p2_marker = _confirm_marker(trade, trade.player2_id)
    embed.add_field(
        name=f"{player1_name} offers {p1_marker}",
        value=_offer_text(trade.player1_cards) if trade.player1_cards else "*no cards yet*",
        inline=True,
    )
    embed.add_field(
        name=f"{player2_name} offers {p2_marker}",
        value=_offer_text(trade.player2_cards) if trade.player2_cards else "*no cards yet*",
        inline=True,
    )
    if completed:
        embed.set_footer(text="Trade complete \u2014 cards have changed owners.")
    elif cancelled:
        embed.set_footer(text="Trade cancelled.")
    else:
        embed.set_footer(
            text=f"Up to {MAX_OFFER_CARDS} cards per side - both players must confirm."
        )
    return embed


def _confirm_marker(trade: Trade, player_id: int) -> str:
    confirmed_states = {
        TradeState.BOTH_CONFIRMED,
        TradeState.COMPLETED,
    }
    if trade.state in confirmed_states:
        return "\u2705"
    if trade.state is TradeState.PLAYER1_CONFIRMED and player_id == trade.player1_id:
        return "\u2705"
    if trade.state is TradeState.PLAYER2_CONFIRMED and player_id == trade.player2_id:
        return "\u2705"
    return "\u23F3"


def _offer_text(cards: tuple[TradeCard, ...]) -> str:
    return "\n".join(fmt.card_line(card) for card in cards)


class OfferCardSelect(discord.ui.Select["OfferEditorView"]):
    def __init__(self, options: list[discord.SelectOption]) -> None:
        super().__init__(
            placeholder="Pick the cards you are offering\u2026",
            options=options,
            min_values=0,
            max_values=min(MAX_OFFER_CARDS, max(1, len(options))),
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        assert view is not None
        trade_view = view.trade_view
        ownership_ids = [UUID(value) for value in self.values]
        try:
            trade = await trade_view.container.trade.add_cards(
                trade_view.trade_id,
                interaction.user.id,
                ownership_ids,
            )
        except TradeCardNotOwnedError:
            await interaction.response.send_message(
                "One of those cards is no longer yours "
                "(did you sell or trade it away?).",
                ephemeral=True,
            )
            return
        except (TradeNotFoundError, TradeInvalidStateError, TradeNotParticipantError):
            await interaction.response.send_message(
                "This trade can no longer be modified.",
                ephemeral=True,
            )
            return

        picked = len(ownership_ids)
        await interaction.response.send_message(
            f"\u2705 Offer updated ({picked} card{'s' if picked != 1 else ''}).",
            ephemeral=True,
        )
        await trade_view.apply_trade(trade, editor=interaction.user)


class OfferEditorView(discord.ui.View):
    """Ephemeral inventory picker for one side of a trade."""

    def __init__(self, trade_view: TradeSessionView) -> None:
        super().__init__(timeout=120)
        self.trade_view = trade_view

    async def load_options(self, player_id: int) -> int:
        page = await self.trade_view.container.inventory.list_cards(
            player_id,
            sort=InventorySort.NEWEST,
            page=1,
            page_size=25,
        )
        trade = await self.trade_view.container.trade.get_trade(
            self.trade_view.trade_id
        )
        currently_offered = {c.ownership_id for c in trade.cards_for(player_id)}
        options = [
            discord.SelectOption(
                label=f"{card.character_name} #{card.print_number}"[:100],
                value=str(card.ownership_id),
                description=f"{card.series_name} · {card.rarity.value}"[:100],
                emoji=fmt.rarity_icon(card.rarity),
                default=card.ownership_id in currently_offered,
            )
            for card in page.items[:25]
        ]
        if options:
            self.add_item(OfferCardSelect(options))
        return len(options)


class TradeSessionView(discord.ui.View):
    """Live trade session between two specific players."""

    def __init__(
        self,
        container: AppContainer,
        trade_id: UUID,
        player1_id: int,
        player2_id: int,
        player1_name: str,
        player2_name: str,
    ) -> None:
        super().__init__(timeout=900)
        self.container = container
        self.trade_id = trade_id
        self.player1_id = player1_id
        self.player2_id = player2_id
        self.player1_name = player1_name
        self.player2_name = player2_name
        self._message: discord.Message | None = None
        self._lock = asyncio.Lock()

    def bind_message(self, message: discord.Message) -> None:
        self._message = message

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id not in (self.player1_id, self.player2_id):
            await interaction.response.send_message(
                "This trade is between "
                f"<@{self.player1_id}> and <@{self.player2_id}>.",
                ephemeral=True,
            )
            return False
        return True

    async def apply_trade(self, trade: Trade, *, editor: discord.abc.User) -> None:
        await self._edit_main_message(trade)
        logger.info(
            "trade_offer_updated",
            extra={"trade_id": str(self.trade_id), "editor_id": editor.id},
        )

    async def _edit_main_message(self, trade: Trade) -> None:
        if self._message is None:
            return
        embed = trade_status_embed(trade, self.player1_name, self.player2_name)
        file = await self._render_sheet(trade)
        try:
            if file is None:
                await self._message.edit(embed=embed, attachments=[], view=self)
            else:
                await self._message.edit(embed=embed, attachments=[file], view=self)
        except discord.HTTPException:
            logger.exception(
                "trade_message_edit_failed",
                extra={"trade_id": str(self.trade_id)},
            )

    async def _render_sheet(self, trade: Trade) -> discord.File | None:
        p1_images = await asyncio.gather(
            *(render_trade_card(self.container, card) for card in trade.player1_cards)
        )
        p2_images = await asyncio.gather(
            *(render_trade_card(self.container, card) for card in trade.player2_cards)
        )
        sheet = await asyncio.to_thread(
            compose_trade_sheet,
            self.container,
            list(p1_images),
            list(p2_images),
        )
        if sheet is None:
            return None
        return card_attachment(sheet, f"trade-{self.trade_id.hex[:8]}")

    def _finish(self, trade: Trade) -> None:
        fmt.disable_view_items(self)
        asyncio.create_task(self._edit_main_message(trade))
        self.stop()

    @discord.ui.button(
        label="Edit my offer",
        emoji="\u270F\uFE0F",
        style=discord.ButtonStyle.secondary,
        custom_id="trade:offer",
    )
    async def edit_offer(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button[TradeSessionView],
    ) -> None:
        editor = OfferEditorView(self)
        count = await editor.load_options(interaction.user.id)
        if count == 0:
            await interaction.response.send_message(
                "You do not own any cards to offer yet.",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            f"Select up to {MAX_OFFER_CARDS} cards from your inventory "
            "(your current offer is preselected):",
            view=editor,
            ephemeral=True,
        )

    @discord.ui.button(
        label="Confirm trade",
        emoji="\u2705",
        style=discord.ButtonStyle.success,
        custom_id="trade:confirm",
    )
    async def confirm(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button[TradeSessionView],
    ) -> None:
        async with self._lock:
            try:
                trade = await self.container.trade.confirm(
                    self.trade_id,
                    interaction.user.id,
                )
            except (TradeNotFoundError, TradeNotParticipantError, TradeInvalidStateError):
                await interaction.response.send_message(
                    "This trade can no longer be confirmed.",
                    ephemeral=True,
                )
                return

            await interaction.response.defer()
            if trade.state is TradeState.COMPLETED:
                self._finish(trade)
                await interaction.followup.send(
                    "\U0001F389 Trade complete! Cards have been exchanged."
                )
            else:
                await self._edit_main_message(trade)

    @discord.ui.button(
        label="Cancel trade",
        emoji="\u274C",
        style=discord.ButtonStyle.danger,
        custom_id="trade:cancel",
    )
    async def cancel(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button[TradeSessionView],
    ) -> None:
        async with self._lock:
            try:
                await self.container.trade.cancel(self.trade_id, interaction.user.id)
                trade = await self.container.trade.get_trade(self.trade_id)
            except (TradeNotFoundError, TradeNotParticipantError, TradeInvalidStateError):
                await interaction.response.send_message(
                    "This trade can no longer be cancelled.",
                    ephemeral=True,
                )
                return
            await interaction.response.defer()
            self._finish(trade)

    async def on_timeout(self) -> None:
        try:
            trade = await self.container.trade.get_trade(self.trade_id)
        except TradeNotFoundError:
            return
        if trade.is_active:
            try:
                await self.container.trade.cancel(self.trade_id, self.player1_id)
                trade = await self.container.trade.get_trade(self.trade_id)
            except (TradeNotFoundError, TradeNotParticipantError, TradeInvalidStateError):
                logger.warning(
                    "trade_timeout_cancel_failed",
                    extra={"trade_id": str(self.trade_id)},
                )
        fmt.disable_view_items(self)
        if self._message is not None:
            embed = trade_status_embed(trade, self.player1_name, self.player2_name)
            if trade.state is TradeState.CANCELLED:
                embed.set_footer(text="Trade timed out and was cancelled.")
            try:
                await self._message.edit(embed=embed, view=self)
            except discord.HTTPException:
                logger.exception(
                    "trade_timeout_edit_failed",
                    extra={"trade_id": str(self.trade_id)},
                )
