from __future__ import annotations

import unittest
from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID, uuid4

from larpcard.economy.domain import Balance, CurrencyType, TransactionType
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
from larpcard.marketplace.service import MarketplaceService

from tests.test_economy import MemoryBalanceStore, MemoryTransactionLog


class MemoryMarketplaceRepository:
    def __init__(self) -> None:
        self._listings: dict[UUID, Listing] = {}
        self._ownership_listings: dict[UUID, int] = {}

    async def create_listing(
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
        created_at: datetime,
    ) -> Listing:
        lid = uuid4()
        listing = Listing(
            id=lid,
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
            status=ListingStatus.ACTIVE,
            created_at=created_at,
            sold_at=None,
            buyer_id=None,
            image_path=image_path,
        )
        self._listings[lid] = listing
        self._ownership_listings[ownership_id] = (
            self._ownership_listings.get(ownership_id, 0) + 1
        )
        return listing

    async def get_active_listing(self, listing_id: UUID) -> Listing | None:
        listing = self._listings.get(listing_id)
        if listing is None or listing.status != ListingStatus.ACTIVE:
            return None
        return listing

    async def get_listing(self, listing_id: UUID) -> Listing | None:
        return self._listings.get(listing_id)

    async def mark_sold(
        self,
        listing_id: UUID,
        buyer_id: int,
        sold_at: datetime,
    ) -> None:
        listing = self._listings.get(listing_id)
        if listing:
            self._listings[listing_id] = Listing(
                id=listing.id,
                seller_id=listing.seller_id,
                ownership_id=listing.ownership_id,
                definition_id=listing.definition_id,
                character_name=listing.character_name,
                series_name=listing.series_name,
                rarity=listing.rarity,
                print_number=listing.print_number,
                edition=listing.edition,
                variant=listing.variant,
                price=listing.price,
                status=ListingStatus.SOLD,
                created_at=listing.created_at,
                sold_at=sold_at,
                buyer_id=buyer_id,
                image_path=listing.image_path,
            )

    async def cancel_listing(self, listing_id: UUID) -> None:
        listing = self._listings.get(listing_id)
        if listing:
            self._listings[listing_id] = Listing(
                id=listing.id,
                seller_id=listing.seller_id,
                ownership_id=listing.ownership_id,
                definition_id=listing.definition_id,
                character_name=listing.character_name,
                series_name=listing.series_name,
                rarity=listing.rarity,
                print_number=listing.print_number,
                edition=listing.edition,
                variant=listing.variant,
                price=listing.price,
                status=ListingStatus.CANCELLED,
                created_at=listing.created_at,
                sold_at=None,
                buyer_id=None,
                image_path=listing.image_path,
            )

    async def query(
        self,
        *,
        filters: ListingFilters,
        sort: ListingSort,
        page: int,
        page_size: int,
    ) -> ListingPage:
        items = [
            l for l in self._listings.values() if l.status == ListingStatus.ACTIVE
        ]
        if filters.rarity is not None:
            items = [l for l in items if l.rarity == filters.rarity]
        if filters.series_name:
            items = [
                l
                for l in items
                if filters.series_name.lower() in l.series_name.lower()
            ]
        if filters.character_name:
            items = [
                l
                for l in items
                if filters.character_name.lower() in l.character_name.lower()
            ]
        if filters.seller_id is not None:
            items = [l for l in items if l.seller_id == filters.seller_id]
        if filters.min_price is not None:
            items = [l for l in items if l.price >= filters.min_price]
        if filters.max_price is not None:
            items = [l for l in items if l.price <= filters.max_price]
        if filters.search:
            p = filters.search.lower()
            items = [
                l
                for l in items
                if p in l.character_name.lower() or p in l.series_name.lower()
            ]

        reverse = True
        match sort:
            case ListingSort.NEWEST:
                items.sort(key=lambda l: l.created_at, reverse=True)
            case ListingSort.OLDEST:
                items.sort(key=lambda l: l.created_at, reverse=False)
            case ListingSort.PRICE_ASC:
                items.sort(key=lambda l: l.price, reverse=False)
            case ListingSort.PRICE_DESC:
                items.sort(key=lambda l: l.price, reverse=True)
            case ListingSort.RARITY:
                items.sort(key=lambda l: l.rarity, reverse=True)

        total = len(items)
        total_pages = max(1, (total + page_size - 1) // page_size)
        offset = (page - 1) * page_size
        return ListingPage(
            items=tuple(items[offset : offset + page_size]),
            total_count=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )

    async def count_active_by_ownership(
        self,
        ownership_id: UUID,
    ) -> int:
        return self._ownership_listings.get(ownership_id, 0)


class MarketplaceServiceTests(unittest.IsolatedAsyncioTestCase):
    def make_service(
        self,
    ) -> tuple[MarketplaceService, MemoryMarketplaceRepository, EconomyService]:
        repo = MemoryMarketplaceRepository()
        balances = MemoryBalanceStore()
        txns = MemoryTransactionLog()
        economy = EconomyService(balances=balances, transactions=txns, rewards=...)
        # patch rewards since we don't test them here
        economy._rewards = None  # type: ignore[assignment]

        service = MarketplaceService(
            repository=repo,
            economy=economy,
            marketplace_fee_percent=5,
        )
        return service, repo, economy

    async def test_list_card_creates_active_listing(self) -> None:
        service, repo, _ = self.make_service()
        listing = await service.list_card(
            seller_id=100,
            ownership_id=uuid4(),
            definition_id=uuid4(),
            character_name="Gojo Satoru",
            series_name="Jujutsu Kaisen",
            rarity="legendary",
            print_number=42,
            edition="standard",
            variant="base",
            price=5000,
            image_path="artwork/card.png",
        )
        self.assertEqual(listing.status, ListingStatus.ACTIVE)
        self.assertEqual(listing.seller_id, 100)
        self.assertEqual(listing.price, 5000)

    async def test_cannot_list_same_card_twice(self) -> None:
        service, _, _ = self.make_service()
        oid = uuid4()
        await service.list_card(
            seller_id=100,
            ownership_id=oid,
            definition_id=uuid4(),
            character_name="Gojo",
            series_name="JJK",
            rarity="common",
            print_number=1,
            edition="standard",
            variant="base",
            price=1000,
            image_path="artwork/card.png",
        )
        with self.assertRaises(ListingError):
            await service.list_card(
                seller_id=100,
                ownership_id=oid,
                definition_id=uuid4(),
                character_name="Gojo",
                series_name="JJK",
                rarity="common",
                print_number=1,
                edition="standard",
                variant="base",
                price=1000,
                image_path="artwork/card.png",
            )

    async def test_buy_card_transfers_currency(self) -> None:
        service, repo, economy = self.make_service()
        # give buyer coins
        await economy.add_currency(200, CurrencyType.COINS, 10000)

        listing = await service.list_card(
            seller_id=100,
            ownership_id=uuid4(),
            definition_id=uuid4(),
            character_name="Gojo",
            series_name="JJK",
            rarity="legendary",
            print_number=1,
            edition="standard",
            variant="base",
            price=5000,
            image_path="artwork/card.png",
        )

        await service.buy_card(listing.id, buyer_id=200)

        seller_balance = await economy.get_balance(100)
        buyer_balance = await economy.get_balance(200)
        self.assertEqual(seller_balance.coins, 4750)  # 5000 - 5% fee
        self.assertEqual(buyer_balance.coins, 5000)  # 10000 - 5000

    async def test_buy_card_marks_as_sold(self) -> None:
        service, repo, economy = self.make_service()
        await economy.add_currency(200, CurrencyType.COINS, 10000)

        listing = await service.list_card(
            seller_id=100,
            ownership_id=uuid4(),
            definition_id=uuid4(),
            character_name="Gojo",
            series_name="JJK",
            rarity="common",
            print_number=1,
            edition="standard",
            variant="base",
            price=1000,
            image_path="artwork/card.png",
        )

        result = await service.buy_card(listing.id, buyer_id=200)
        self.assertEqual(result.status, ListingStatus.SOLD)

    async def test_buy_own_listing_raises_error(self) -> None:
        service, repo, economy = self.make_service()
        await economy.add_currency(100, CurrencyType.COINS, 50000)

        listing = await service.list_card(
            seller_id=100,
            ownership_id=uuid4(),
            definition_id=uuid4(),
            character_name="Gojo",
            series_name="JJK",
            rarity="common",
            print_number=1,
            edition="standard",
            variant="base",
            price=1000,
            image_path="artwork/card.png",
        )

        with self.assertRaises(CannotBuyOwnListingError):
            await service.buy_card(listing.id, buyer_id=100)

    async def test_buy_already_sold_listing_raises_error(self) -> None:
        service, repo, economy = self.make_service()
        await economy.add_currency(200, CurrencyType.COINS, 50000)
        await economy.add_currency(300, CurrencyType.COINS, 50000)

        listing = await service.list_card(
            seller_id=100,
            ownership_id=uuid4(),
            definition_id=uuid4(),
            character_name="Gojo",
            series_name="JJK",
            rarity="common",
            print_number=1,
            edition="standard",
            variant="base",
            price=1000,
            image_path="artwork/card.png",
        )

        await service.buy_card(listing.id, buyer_id=200)

        with self.assertRaises((SoldOutError, ListingNotFoundError)):
            await service.buy_card(listing.id, buyer_id=300)

    async def test_cancel_listing(self) -> None:
        service, repo, _ = self.make_service()
        listing = await service.list_card(
            seller_id=100,
            ownership_id=uuid4(),
            definition_id=uuid4(),
            character_name="Gojo",
            series_name="JJK",
            rarity="common",
            print_number=1,
            edition="standard",
            variant="base",
            price=1000,
            image_path="artwork/card.png",
        )

        await service.cancel_listing(listing.id, seller_id=100)
        cancelled = await repo.get_active_listing(listing.id)
        self.assertIsNone(cancelled)

    async def test_cancel_listing_wrong_seller_raises_error(self) -> None:
        service, repo, _ = self.make_service()
        listing = await service.list_card(
            seller_id=100,
            ownership_id=uuid4(),
            definition_id=uuid4(),
            character_name="Gojo",
            series_name="JJK",
            rarity="common",
            print_number=1,
            edition="standard",
            variant="base",
            price=1000,
            image_path="artwork/card.png",
        )

        with self.assertRaises(NotOwnerError):
            await service.cancel_listing(listing.id, seller_id=999)

    async def test_search_filters_by_rarity(self) -> None:
        service, repo, _ = self.make_service()
        for i in range(3):
            await service.list_card(
                seller_id=100,
                ownership_id=uuid4(),
                definition_id=uuid4(),
                character_name=f"Char {i}",
                series_name="Series",
                rarity="legendary" if i % 2 == 0 else "common",
                print_number=i + 1,
                edition="standard",
                variant="base",
                price=1000 * (i + 1),
                image_path="artwork/card.png",
            )

        page = await service.search(filters=ListingFilters(rarity="legendary"))
        self.assertEqual(page.total_count, 2)

    async def test_search_pagination(self) -> None:
        service, repo, _ = self.make_service()
        for i in range(5):
            await service.list_card(
                seller_id=100,
                ownership_id=uuid4(),
                definition_id=uuid4(),
                character_name=f"Char {i}",
                series_name="Series",
                rarity="common",
                print_number=i + 1,
                edition="standard",
                variant="base",
                price=1000,
                image_path="artwork/card.png",
            )

        page = await service.search(page=1, page_size=2)
        self.assertEqual(len(page.items), 2)
        self.assertEqual(page.total_count, 5)
        self.assertEqual(page.total_pages, 3)

    async def test_sort_by_price(self) -> None:
        service, repo, _ = self.make_service()
        for price in [5000, 1000, 3000]:
            await service.list_card(
                seller_id=100,
                ownership_id=uuid4(),
                definition_id=uuid4(),
                character_name="Char",
                series_name="Series",
                rarity="common",
                print_number=1,
                edition="standard",
                variant="base",
                price=price,
                image_path="artwork/card.png",
            )

        page = await service.search(sort=ListingSort.PRICE_ASC, page_size=10)
        prices = [l.price for l in page.items]
        self.assertEqual(prices, [1000, 3000, 5000])
