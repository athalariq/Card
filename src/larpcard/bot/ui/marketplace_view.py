from __future__ import annotations

import logging
from uuid import UUID

import discord

from larpcard.bot.container import AppContainer
from larpcard.bot.ui import formatting as fmt
from larpcard.bot.ui.rendering import card_attachment, render_listing_card
from larpcard.economy.domain import InsufficientFundsError
from larpcard.inventory.domain import InventoryCard, InventorySort
from larpcard.marketplace.domain import (
    CannotBuyOwnListingError,
    Listing,
    ListingError,
    ListingFilters,
    ListingNotFoundError,
    ListingPage,
    ListingSort,
    NotOwnerError,
    SoldOutError,
)

logger = logging.getLogger(__name__)

_SORT_LABELS: dict[ListingSort, str] = {
    ListingSort.NEWEST: "Newest listings",
    ListingSort.OLDEST: "Oldest listings",
    ListingSort.PRICE_ASC: "Price: low to high",
    ListingSort.PRICE_DESC: "Price: high to low",
    ListingSort.RARITY: "Highest rarity",
}


def listing_embed(
    listing: Listing,
    *,
    marketplace_fee_percent: int,
    page: ListingPage | None = None,
    viewer_id: int | None = None,
) -> discord.Embed:
    embed = discord.Embed(
        title=f"{listing.character_name}",
        description=(
            f"{listing.series_name}\n"
            f"{fmt.rarity_icon(listing.rarity)} {listing.rarity.value.title()}\n"
            f"Print `#{listing.print_number}`"
        ),
        color=fmt.embed_color(listing.rarity),
    )
    embed.add_field(
        name="Price",
        value=f"{fmt.COIN} **{listing.price:,}**",
        inline=True,
    )
    embed.add_field(
        name="Seller",
        value=f"<@{listing.seller_id}>",
        inline=True,
    )
    own_listing = viewer_id is not None and listing.seller_id == viewer_id
    proceeds = listing.price - listing.price * marketplace_fee_percent // 100
    embed.add_field(
        name="Seller receives",
        value=f"{fmt.COIN} {proceeds:,}",
        inline=True,
    )
    footer_bits = []
    if page is not None:
        footer_bits.append(f"Listing {page.page:,} of {page.total_count:,}")
    footer_bits.append(f"fee {marketplace_fee_percent}%")
    if own_listing:
        footer_bits.append("your listing")
    embed.set_footer(text=" \u00b7 ".join(footer_bits))
    return embed


def sold_listing_embed(listing: Listing, buyer_id: int) -> discord.Embed:
    embed = discord.Embed(
        title=f"SOLD \u2013 {listing.character_name}",
        description=(
            f"{listing.series_name}\n"
            f"{fmt.rarity_icon(listing.rarity)} {listing.rarity.value.title()}\n"
            f"Print `#{listing.print_number}`\n\n"
            f"Purchased by <@{buyer_id}> for {fmt.COIN} **{listing.price:,}**."
        ),
        color=discord.Color.green(),
    )
    return embed


class PurchaseConfirmView(discord.ui.View):
    def __init__(
        self,
        container: AppContainer,
        listing: Listing,
        buyer_id: int,
    ) -> None:
        super().__init__(timeout=60)
        self._container = container
        self._listing = listing
        self._buyer_id = buyer_id
        self.result: Listing | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self._buyer_id

    @discord.ui.button(
        label="Confirm purchase",
        emoji=fmt.COIN,
        style=discord.ButtonStyle.success,
        custom_id="market:buy:confirm",
    )
    async def confirm(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button[PurchaseConfirmView],
    ) -> None:
        try:
            self.result = await self._container.marketplace.buy_card(
                self._listing.id,
                self._buyer_id,
            )
        except CannotBuyOwnListingError:
            await interaction.response.send_message(
                "You cannot buy your own listing.",
                ephemeral=True,
            )
            return
        except (ListingNotFoundError, SoldOutError):
            await interaction.response.send_message(
                "This listing is no longer available.",
                ephemeral=True,
            )
            return
        except InsufficientFundsError as error:
            await interaction.response.send_message(
                f"Not enough coins: the card costs {fmt.COIN} "
                f"**{error.requested:,}** but you only have "
                f"**{error.available:,}**.",
                ephemeral=True,
            )
            return

        fmt.disable_view_items(self)
        await interaction.response.edit_message(
            content=(
                f"You bought {fmt.card_line(self.result)} "
                f"for {fmt.COIN} **{self.result.price:,}**!"
            ),
            view=self,
        )
        self.stop()

    @discord.ui.button(
        label="Cancel",
        style=discord.ButtonStyle.secondary,
        custom_id="market:buy:cancel",
    )
    async def cancel(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button[PurchaseConfirmView],
    ) -> None:
        fmt.disable_view_items(self)
        await interaction.response.edit_message(content="Purchase cancelled.", view=self)
        self.stop()


class MarketplaceBrowseView(discord.ui.View):
    """One-listing public browser with a buy button."""

    def __init__(
        self,
        container: AppContainer,
        filters: ListingFilters,
        sort: ListingSort,
        viewer_id: int,
    ) -> None:
        super().__init__(timeout=300)
        self._container = container
        self._filters = filters
        self._sort = sort
        self._viewer_id = viewer_id
        self._page = 1
        self._data: ListingPage | None = None

    @property
    def current_listing(self) -> Listing | None:
        if self._data is None or not self._data.items:
            return None
        return self._data.items[0]

    async def load_page(self) -> ListingPage:
        data = await self._container.marketplace.search(
            filters=self._filters,
            sort=self._sort,
            page=self._page,
            page_size=1,
        )
        self._page = data.page
        self._data = data
        return data

    async def build(self) -> tuple[discord.Embed, discord.File | None]:
        data = await self.load_page()
        self._sync_buttons(data)
        listing = self.current_listing
        if listing is None:
            embed = discord.Embed(
                title="\U0001F9F9 No listings found",
                description="Nothing on the marketplace matches these filters.",
                color=discord.Color.dark_grey(),
            )
            return embed, None
        embed = listing_embed(
            listing,
            marketplace_fee_percent=self._container.marketplace.fee_percent,
            page=data,
            viewer_id=self._viewer_id,
        )
        file = card_attachment(
            await render_listing_card(self._container, listing),
            f"listing-{listing.id.hex[:8]}",
        )
        embed.set_image(url=f"attachment://{file.filename}")
        return embed, file

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

    def _sync_buttons(self, data: ListingPage) -> None:
        empty = data.total_count == 0
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                if item.custom_id == "market:prev":
                    item.disabled = empty or not data.has_previous
                elif item.custom_id == "market:next":
                    item.disabled = empty or not data.has_next
                elif item.custom_id == "market:buy":
                    listing = self.current_listing
                    item.disabled = (
                        empty
                        or listing is None
                        or listing.seller_id == self._viewer_id
                    )
                    listing_price = listing.price if listing else 0
                    item.label = (
                        f"Buy for {listing_price:,} coins"
                        if listing is not None and listing.seller_id != self._viewer_id
                        else "Buy"
                    )

    @discord.ui.button(
        label="Prev",
        emoji="\u25C0\uFE0F",
        style=discord.ButtonStyle.secondary,
        custom_id="market:prev",
    )
    async def previous_page(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button[MarketplaceBrowseView],
    ) -> None:
        self._page = max(1, self._page - 1)
        await self.refresh(interaction)

    @discord.ui.button(
        label="Next",
        emoji="\u25B6\uFE0F",
        style=discord.ButtonStyle.secondary,
        custom_id="market:next",
    )
    async def next_page(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button[MarketplaceBrowseView],
    ) -> None:
        self._page += 1
        await self.refresh(interaction)

    @discord.ui.button(
        label="Buy",
        emoji=fmt.COIN,
        style=discord.ButtonStyle.success,
        custom_id="market:buy",
    )
    async def buy(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button[MarketplaceBrowseView],
    ) -> None:
        listing = self.current_listing
        if listing is None:
            await interaction.response.send_message(
                "There is nothing to buy here.",
                ephemeral=True,
            )
            return
        if listing.seller_id == interaction.user.id:
            await interaction.response.send_message(
                "You cannot buy your own listing.\n"
                "Cancel it from `/market my-listings` instead.",
                ephemeral=True,
            )
            return
        confirm = PurchaseConfirmView(self._container, listing, interaction.user.id)
        balance = await self._container.economy.get_balance(interaction.user.id)
        await interaction.response.send_message(
            f"Buy {fmt.card_line(listing)} "
            f"for {fmt.COIN} **{listing.price:,}**?\n"
            f"Your balance: {fmt.COIN} **{balance.coins:,}**",
            view=confirm,
            ephemeral=True,
        )
        await confirm.wait()
        if confirm.result is not None:
            public = interaction.message
            if public is not None:
                try:
                    await public.edit(
                        embed=sold_listing_embed(confirm.result, interaction.user.id),
                        view=SoldListingView(),
                    )
                except discord.HTTPException:
                    logger.exception(
                        "marketplace_sold_message_edit_failed",
                        extra={"listing_id": str(confirm.result.id)},
                    )
            await interaction.followup.send(
                f"{interaction.user.mention} bought "
                f"{fmt.card_line(confirm.result)} "
                f"for {fmt.COIN} **{confirm.result.price:,}**!"
            )
            self.stop()

    async def on_timeout(self) -> None:
        fmt.disable_view_items(self)


class SoldListingView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)
        button = discord.ui.Button[discord.ui.View](
            label="Sold",
            style=discord.ButtonStyle.secondary,
            disabled=True,
            custom_id="market:sold",
        )
        self.add_item(button)


class ListCardModal(discord.ui.Modal, title="List card on the marketplace"):
    price: discord.ui.TextInput[ListCardModal] = discord.ui.TextInput(
        label="Price in coins",
        placeholder="e.g. 500",
        min_length=1,
        max_length=8,
        required=True,
    )

    def __init__(
        self,
        container: AppContainer,
        seller_id: int,
        *,
        ownership_id: UUID,
        definition_id: UUID,
        character_name: str,
        series_name: str,
        rarity: str,
        print_number: int,
        edition: str,
        variant: str,
        image_path: str,
    ) -> None:
        super().__init__()
        self._container = container
        self._seller_id = seller_id
        self._ownership_id = ownership_id
        self._definition_id = definition_id
        self._character_name = character_name
        self._series_name = series_name
        self._rarity = rarity
        self._print_number = print_number
        self._edition = edition
        self._variant = variant
        self._image_path = image_path

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            price = int(str(self.price.value).strip().replace(",", ""))
        except ValueError:
            await interaction.response.send_message(
                "That is not a valid price. Use whole coins, e.g. `500`.",
                ephemeral=True,
            )
            return

        marketplace = self._container.marketplace
        if not marketplace.min_price <= price <= marketplace.max_price:
            await interaction.response.send_message(
                f"Price must be between {marketplace.min_price:,} "
                f"and {marketplace.max_price:,} coins.",
                ephemeral=True,
            )
            return

        try:
            listing = await marketplace.list_card(
                seller_id=self._seller_id,
                ownership_id=self._ownership_id,
                definition_id=self._definition_id,
                character_name=self._character_name,
                series_name=self._series_name,
                rarity=self._rarity,
                print_number=self._print_number,
                edition=self._edition,
                variant=self._variant,
                price=price,
                image_path=self._image_path,
            )
        except ListingError as error:
            await interaction.response.send_message(
                f"Could not list this card: {error}",
                ephemeral=True,
            )
            return

        proceeds = marketplace.seller_proceeds(price)
        await interaction.response.send_message(
            f"\U0001F4B0 Listed **{listing.character_name}** "
            f"`#{listing.print_number}` for {fmt.COIN} **{price:,}**.\n"
            f"When it sells you receive **{proceeds:,}** coins "
            f"(marketplace fee {marketplace.fee_percent}%).\n"
            "Manage it with `/market my-listings`.",
            ephemeral=True,
        )
        logger.info(
            "card_listed_via_modal",
            extra={"listing_id": str(listing.id), "price": price},
        )


class SellCardSelect(discord.ui.Select["SellFlowView"]):
    def __init__(self, options: list[discord.SelectOption]) -> None:
        super().__init__(
            placeholder="Pick a card to list\u2026",
            options=options,
            min_values=1,
            max_values=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        assert view is not None
        card = view.cards_by_id.get(self.values[0])
        if card is None:
            await interaction.response.send_message(
                "That card is no longer available.",
                ephemeral=True,
            )
            return
        modal = ListCardModal(
            view.container,
            view.seller_id,
            ownership_id=card.ownership_id,
            definition_id=card.definition_id,
            character_name=card.character_name,
            series_name=card.series_name,
            rarity=card.rarity.value,
            print_number=card.print_number,
            edition=card.edition,
            variant=card.variant,
            image_path=card.image_path,
        )
        await interaction.response.send_modal(modal)


class SellFlowView(discord.ui.View):
    """Ephemeral flow: pick an owned card, then a price, to create a listing."""

    def __init__(self, container: AppContainer, seller_id: int) -> None:
        super().__init__(timeout=120)
        self.container = container
        self.seller_id = seller_id
        self.cards_by_id: dict[str, InventoryCard] = {}

    async def load_cards(self) -> int:
        page = await self.container.inventory.list_cards(
            self.seller_id,
            sort=InventorySort.NEWEST,
            page=1,
            page_size=25,
        )
        options: list[discord.SelectOption] = []
        for card in page.items:
            label = f"{card.character_name} #{card.print_number}"[:100]
            description = (
                f"{card.series_name} · {card.rarity.value}"[:100]
            )
            option = discord.SelectOption(
                label=label,
                value=str(card.ownership_id),
                description=description,
                emoji=fmt.rarity_icon(card.rarity),
            )
            self.cards_by_id[str(card.ownership_id)] = card
            options.append(option)
        if options:
            self.add_item(SellCardSelect(options))
        return len(options)


class MyListingsView(discord.ui.View):
    """Ephemeral paginated view of the seller's own active listings."""

    def __init__(self, container: AppContainer, seller_id: int) -> None:
        super().__init__(timeout=300)
        self._container = container
        self._seller_id = seller_id
        self._page = 1
        self._data: ListingPage | None = None

    @property
    def current_listing(self) -> Listing | None:
        if self._data is None or not self._data.items:
            return None
        return self._data.items[0]

    async def build(self) -> tuple[discord.Embed, discord.File | None]:
        self._data = await self._container.marketplace.search(
            filters=ListingFilters(seller_id=self._seller_id),
            sort=ListingSort.NEWEST,
            page=self._page,
            page_size=1,
        )
        self._page = self._data.page
        self._sync_buttons(self._data)
        listing = self.current_listing
        if listing is None:
            return (
                discord.Embed(
                    title="You have no active listings",
                    description="List cards with `/market sell`.",
                    color=discord.Color.dark_grey(),
                ),
                None,
            )
        embed = listing_embed(
            listing,
            marketplace_fee_percent=self._container.marketplace.fee_percent,
            page=self._data,
            viewer_id=self._seller_id,
        )
        file = card_attachment(
            await render_listing_card(self._container, listing),
            f"listing-{listing.id.hex[:8]}",
        )
        embed.set_image(url=f"attachment://{file.filename}")
        return embed, file

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

    def _sync_buttons(self, data: ListingPage) -> None:
        empty = data.total_count == 0
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                if item.custom_id == "mine:prev":
                    item.disabled = empty or not data.has_previous
                elif item.custom_id == "mine:next":
                    item.disabled = empty or not data.has_next
                elif item.custom_id == "mine:cancel":
                    item.disabled = empty

    @discord.ui.button(
        label="Prev",
        emoji="\u25C0\uFE0F",
        style=discord.ButtonStyle.secondary,
        custom_id="mine:prev",
    )
    async def previous_page(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button[MyListingsView],
    ) -> None:
        self._page = max(1, self._page - 1)
        await self.refresh(interaction)

    @discord.ui.button(
        label="Next",
        emoji="\u25B6\uFE0F",
        style=discord.ButtonStyle.secondary,
        custom_id="mine:next",
    )
    async def next_page(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button[MyListingsView],
    ) -> None:
        self._page += 1
        await self.refresh(interaction)

    @discord.ui.button(
        label="Cancel listing",
        emoji="\u274C",
        style=discord.ButtonStyle.danger,
        custom_id="mine:cancel",
    )
    async def cancel_listing(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button[MyListingsView],
    ) -> None:
        listing = self.current_listing
        if listing is None:
            await interaction.response.send_message(
                "Nothing to cancel.",
                ephemeral=True,
            )
            return
        try:
            await self._container.marketplace.cancel_listing(
                listing.id,
                self._seller_id,
            )
        except (ListingNotFoundError, NotOwnerError, SoldOutError):
            await interaction.response.send_message(
                "This listing is no longer active.",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            f"\u2705 Removed **{listing.character_name}** "
            f"`#{listing.print_number}` from the marketplace.",
            ephemeral=True,
        )
        await self._reedit_current_page(interaction)

    async def _reedit_current_page(self, interaction: discord.Interaction) -> None:
        if interaction.message is None:
            return
        embed, file = await self.build()
        if file is None:
            await interaction.message.edit(embed=embed, attachments=[], view=self)
        else:
            await interaction.message.edit(embed=embed, attachments=[file], view=self)

    async def on_timeout(self) -> None:
        fmt.disable_view_items(self)
