from __future__ import annotations

import logging

import discord

from larpcard.bot.container import AppContainer
from larpcard.bot.ui import formatting as fmt
from larpcard.bot.ui.rendering import card_attachment, render_inventory_card
from larpcard.inventory.domain import (
    InventoryCard,
    InventoryFilters,
    InventoryPage,
    InventorySort,
)
from larpcard.marketplace.domain import ListingError

logger = logging.getLogger(__name__)

_SORT_LABELS: dict[InventorySort, str] = {
    InventorySort.NEWEST: "Newest first",
    InventorySort.OLDEST: "Oldest first",
    InventorySort.RARITY: "Highest rarity",
    InventorySort.SERIES: "Sort by series",
    InventorySort.CHARACTER: "Sort by character",
    InventorySort.FAVORITES: "Favorites first",
    InventorySort.DUPLICATES: "Group duplicates",
}


class SellPriceModal(discord.ui.Modal, title="List card on the marketplace"):
    price: discord.ui.TextInput[SellPriceModal] = discord.ui.TextInput(
        label="Price in coins",
        placeholder="e.g. 500",
        min_length=1,
        max_length=8,
        required=True,
    )

    def __init__(self, view: InventoryView, card: InventoryCard) -> None:
        super().__init__()
        self._view = view
        self._card = card

    async def on_submit(self, interaction: discord.Interaction) -> None:
        view = self._view
        card = self._card
        try:
            price = int(str(self.price.value).strip().replace(",", ""))
        except ValueError:
            await interaction.response.send_message(
                "That is not a valid price. Use whole coins, e.g. `500`.",
                ephemeral=True,
            )
            return

        marketplace = view._container.marketplace
        if not marketplace.min_price <= price <= marketplace.max_price:
            await interaction.response.send_message(
                f"Price must be between {marketplace.min_price:,} "
                f"and {marketplace.max_price:,} coins.",
                ephemeral=True,
            )
            return

        try:
            listing = await marketplace.list_card(
                seller_id=view._viewer_id,
                ownership_id=card.ownership_id,
                definition_id=card.definition_id,
                character_name=card.character_name,
                series_name=card.series_name,
                rarity=card.rarity.value,
                print_number=card.print_number,
                edition=card.edition,
                variant=card.variant,
                price=price,
                image_path=card.image_path,
            )
        except ListingError as error:
            await interaction.response.send_message(
                f"Could not list this card: {error}",
                ephemeral=True,
            )
            return

        proceeds = marketplace.seller_proceeds(price)
        await interaction.response.send_message(
            f"\U0001F4B0 Listed {fmt.card_line(card, favorite=card.is_favorite)} "
            f"for **{price:,}** coins.\n"
            f"When it sells you receive **{proceeds:,}** coins "
            f"(marketplace fee {marketplace.fee_percent}%).",
            ephemeral=True,
        )
        logger.info(
            "inventory_card_listed",
            extra={
                "listing_id": str(listing.id),
                "seller_id": view._viewer_id,
                "price": price,
            },
        )


class InventorySortSelect(discord.ui.Select["InventoryView"]):
    def __init__(self, current: InventorySort) -> None:
        options = [
            discord.SelectOption(
                label=label,
                value=sort.value,
                default=sort is current,
            )
            for sort, label in _SORT_LABELS.items()
        ]
        super().__init__(
            placeholder="Sort cards\u2026",
            options=options,
            row=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if self.view is not None:
            self.view._sort = InventorySort(self.values[0])
            self.view._page = 1
            await self.view.refresh(interaction)


class InventoryView(discord.ui.View):
    """Single-card inventory browser owned by the viewer."""

    def __init__(
        self,
        container: AppContainer,
        viewer_id: int,
        filters: InventoryFilters,
        sort: InventorySort,
    ) -> None:
        super().__init__(timeout=300)
        self._container = container
        self._viewer_id = viewer_id
        self._filters = filters
        self._sort = sort
        self._page = 1
        self._data: InventoryPage | None = None
        self.add_item(InventorySortSelect(sort))

    @property
    def current_card(self) -> InventoryCard | None:
        if self._data is None or not self._data.items:
            return None
        return self._data.items[0]

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self._viewer_id:
            await interaction.response.send_message(
                "Only the owner can browse this inventory.",
                ephemeral=True,
            )
            return False
        return True

    async def build(self) -> tuple[discord.Embed, discord.File | None]:
        self._data = await self._container.inventory.list_cards(
            self._viewer_id,
            filters=self._filters,
            sort=self._sort,
            page=self._page,
            page_size=1,
        )
        self._page = self._data.page
        return await self._render_state()

    async def refresh(self, interaction: discord.Interaction) -> None:
        embed, file = await self.build()
        if file is None:
            await interaction.response.edit_message(
                embed=embed, attachments=[], view=self
            )
        else:
            await interaction.response.edit_message(
                embed=embed, attachments=[file], view=self
            )

    async def _render_state(self) -> tuple[discord.Embed, discord.File | None]:
        data = self._data
        if data is None:
            raise RuntimeError("inventory page not loaded")
        card = self.current_card
        self._sync_buttons()

        if card is None:
            embed = discord.Embed(
                title="\U0001F4E3 Inventory is empty",
                description=(
                    "No cards match these filters.\n"
                    "Claim cards with `/drop` and they will appear here!"
                ),
                color=discord.Color.dark_grey(),
            )
            self._apply_filters_footer(embed, total=0)
            return embed, None

        embed = discord.Embed(
            title=card.character_name,
            description=(
                f"{card.series_name}\n"
                f"{fmt.rarity_icon(card.rarity)} {card.rarity.value.title()}"
                f"{' ' + fmt.STAR + ' Favorite' if card.is_favorite else ''}"
            ),
            color=fmt.embed_color(card.rarity),
        )
        embed.add_field(name="Print", value=f"`#{card.print_number}`", inline=True)
        embed.add_field(name="Edition", value=card.edition, inline=True)
        embed.add_field(name="Variant", value=card.variant, inline=True)
        embed.add_field(
            name="Acquired",
            value=f"<t:{int(card.acquired_at.timestamp())}:D>",
            inline=True,
        )
        self._apply_filters_footer(embed, total=data.total_count)
        file = card_attachment(
            await render_inventory_card(self._container, card),
            f"inventory-{card.ownership_id.hex[:8]}",
        )
        embed.set_image(url=f"attachment://{file.filename}")
        return embed, file

    def _apply_filters_footer(self, embed: discord.Embed, *, total: int) -> None:
        data = self._data
        page_info = f"Card {data.page:,} of {max(total, 1):,}" if data else ""
        active: list[str] = []
        f = self._filters
        if f.series_name:
            active.append(f"series={f.series_name}")
        if f.character_name:
            active.append(f"character={f.character_name}")
        if f.rarity:
            active.append(f"rarity={f.rarity.value}")
        if f.search:
            active.append(f"search={f.search}")
        if f.favorites_only:
            active.append("favorites only")
        sort_label = f"sort: {_SORT_LABELS[self._sort].lower()}"
        extras = " · ".join([sort_label, *active])
        embed.set_footer(text=f"{page_info} · {extras}" if page_info else extras)

    def _sync_buttons(self) -> None:
        data = self._data
        empty = data is None or data.total_count == 0
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                if item.custom_id == "inventory:prev":
                    item.disabled = empty or not data or not data.has_previous
                elif item.custom_id == "inventory:next":
                    item.disabled = empty or not data or not data.has_next
                else:
                    item.disabled = empty

    @discord.ui.button(
        label="Prev",
        emoji="\u25C0\uFE0F",
        style=discord.ButtonStyle.secondary,
        custom_id="inventory:prev",
    )
    async def previous_page(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button[InventoryView],
    ) -> None:
        self._page = max(1, self._page - 1)
        await self.refresh(interaction)

    @discord.ui.button(
        label="Next",
        emoji="\u25B6\uFE0F",
        style=discord.ButtonStyle.secondary,
        custom_id="inventory:next",
    )
    async def next_page(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button[InventoryView],
    ) -> None:
        self._page += 1
        await self.refresh(interaction)

    @discord.ui.button(
        label="Favorite",
        emoji=fmt.STAR,
        style=discord.ButtonStyle.primary,
        custom_id="inventory:favorite",
    )
    async def toggle_favorite(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button[InventoryView],
    ) -> None:
        card = self.current_card
        if card is None:
            await interaction.response.send_message(
                "There is no card to favorite.",
                ephemeral=True,
            )
            return
        try:
            await self._container.inventory.toggle_favorite(
                self._viewer_id,
                card.ownership_id,
            )
        except ValueError:
            await interaction.response.send_message(
                "That card is no longer in your inventory.",
                ephemeral=True,
            )
            return
        await self.refresh(interaction)

    @discord.ui.button(
        label="Sell",
        emoji="\U0001F4B0",
        style=discord.ButtonStyle.success,
        custom_id="inventory:sell",
    )
    async def sell_card(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button[InventoryView],
    ) -> None:
        card = self.current_card
        if card is None:
            await interaction.response.send_message(
                "There is no card to sell.",
                ephemeral=True,
            )
            return
        await interaction.response.send_modal(SellPriceModal(self, card))

    async def on_timeout(self) -> None:
        fmt.disable_view_items(self)
