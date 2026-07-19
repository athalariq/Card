from __future__ import annotations

import logging
from datetime import UTC, datetime

from larpcard.economy.domain import CurrencyType, TransactionType
from larpcard.economy.service import EconomyService
from larpcard.marketplace.domain import (
    CannotBuyOwnListingError,
    Listing,
    ListingError,
    ListingFilters,
    ListingNotFoundError,
    ListingPage,
    ListingSort,
    ListingStatus,
    NotOwnerError,
    SoldOutError,
)
from larpcard.marketplace.ports import MarketplaceRepository

logger = logging.getLogger(__name__)


class MarketplaceService:
    def __init__(
        self,
        *,
        repository: MarketplaceRepository,
        economy: EconomyService,
        marketplace_fee_percent: int = 5,
        min_price: int = 1,
        max_price: int = 10_000_000,
    ) -> None:
        self._repository = repository
        self._economy = economy
        self._marketplace_fee_percent = marketplace_fee_percent
        self._min_price = min_price
        self._max_price = max_price

    async def list_card(
        self,
        *,
        seller_id: int,
        ownership_id: UUID,
        definition_id: UUID,
        character_name: str,
        series_name: str,
        rarity: str,
        print_number: int,
        edition: str,
        variant: str,
        price: int,
        image_path: str,
    ) -> Listing:
        if price < self._min_price or price > self._max_price:
            raise ListingError(
                f"price must be between {self._min_price} and {self._max_price}"
            )

        active = await self._repository.count_active_by_ownership(ownership_id)
        if active > 0:
            raise ListingError("this card is already listed on the marketplace")

        now = datetime.now(UTC)
        listing = await self._repository.create_listing(
            seller_id=seller_id,
            ownership_id=ownership_id,
            definition_id=definition_id,
            character_name=character_name,
            series_name=series_name,
            rarity=rarity,
            print_number=print_number,
            edition=edition,
            variant=variant,
            price=price,
            image_path=image_path,
            created_at=now,
        )
        logger.info(
            "card_listed",
            extra={
                "listing_id": str(listing.id),
                "seller_id": seller_id,
                "price": price,
            },
        )
        return listing

    async def buy_card(
        self,
        listing_id: UUID,
        buyer_id: int,
    ) -> Listing:
        listing = await self._repository.get_active_listing(listing_id)
        if listing is None:
            raise ListingNotFoundError(listing_id)
        if listing.status != ListingStatus.ACTIVE:
            raise SoldOutError(listing_id)
        if listing.seller_id == buyer_id:
            raise CannotBuyOwnListingError("cannot buy your own listing")

        fee = listing.price * self._marketplace_fee_percent // 100
        seller_proceeds = listing.price - fee
        now = datetime.now(UTC)

        # Deduct full price from buyer
        await self._economy.remove_currency(
            buyer_id,
            CurrencyType.COINS,
            listing.price,
            transaction_type=TransactionType.MARKETPLACE_PURCHASE,
            reference_id=str(listing_id),
            description=f"marketplace purchase: {listing.character_name}",
        )
        # Credit proceeds to seller (fee is retained by the system)
        await self._economy.add_currency(
            listing.seller_id,
            CurrencyType.COINS,
            seller_proceeds,
            transaction_type=TransactionType.MARKETPLACE_SALE,
            reference_id=str(listing_id),
            description=f"marketplace sale: {listing.character_name}",
        )

        await self._repository.mark_sold(listing_id, buyer_id, now)

        logger.info(
            "card_sold",
            extra={
                "listing_id": str(listing_id),
                "buyer_id": buyer_id,
                "seller_id": listing.seller_id,
                "price": listing.price,
                "fee": fee,
                "seller_proceeds": seller_proceeds,
            },
        )

        # Re-fetch to get updated status
        sold = await self._repository.get_listing(listing_id)
        return sold or listing

    async def cancel_listing(
        self,
        listing_id: UUID,
        seller_id: int,
    ) -> None:
        listing = await self._repository.get_active_listing(listing_id)
        if listing is None:
            raise ListingNotFoundError(listing_id)
        if listing.seller_id != seller_id:
            raise NotOwnerError(listing.ownership_id)
        if listing.status != ListingStatus.ACTIVE:
            raise SoldOutError(listing_id)

        await self._repository.cancel_listing(listing_id)
        logger.info(
            "listing_cancelled",
            extra={
                "listing_id": str(listing_id),
                "seller_id": seller_id,
            },
        )

    async def search(
        self,
        *,
        filters: ListingFilters | None = None,
        sort: ListingSort = ListingSort.NEWEST,
        page: int = 1,
        page_size: int = 20,
    ) -> ListingPage:
        if page < 1:
            page = 1
        if page_size < 1:
            page_size = 1
        if page_size > 100:
            page_size = 100

        return await self._repository.query(
            filters=filters or ListingFilters(),
            sort=sort,
            page=page,
            page_size=page_size,
        )
