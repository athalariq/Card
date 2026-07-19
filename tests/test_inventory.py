from __future__ import annotations

import unittest
from datetime import UTC, datetime
from uuid import UUID, uuid4

from larpcard.cards.domain import Rarity
from larpcard.inventory.domain import (
    InventoryCard,
    InventoryFilters,
    InventoryPage,
    InventorySort,
)
from larpcard.inventory.service import InventoryService


class MemoryInventoryQuery:
    def __init__(self) -> None:
        self._cards: dict[int, list[InventoryCard]] = {}
        self._favorites: set[UUID] = set()

    def add_card(self, player_id: int, card: InventoryCard) -> None:
        self._cards.setdefault(player_id, []).append(card)
        if card.is_favorite:
            self._favorites.add(card.ownership_id)

    async def query(
        self,
        player_id: int,
        *,
        filters: InventoryFilters,
        sort: InventorySort,
        page: int = 1,
        page_size: int = 20,
    ) -> InventoryPage:
        cards = list(self._cards.get(player_id, []))

        if filters.favorites_only:
            cards = [c for c in cards if c.is_favorite]
        if filters.rarity is not None:
            cards = [c for c in cards if c.rarity == filters.rarity]
        if filters.character_name:
            cards = [
                c
                for c in cards
                if filters.character_name.lower() in c.character_name.lower()
            ]
        if filters.series_name:
            cards = [
                c
                for c in cards
                if filters.series_name.lower() in c.series_name.lower()
            ]
        if filters.search:
            pattern = filters.search.lower()
            cards = [
                c
                for c in cards
                if pattern in c.character_name.lower()
                or pattern in c.series_name.lower()
            ]

        match sort:
            case InventorySort.NEWEST:
                cards.sort(key=lambda c: c.acquired_at, reverse=True)
            case InventorySort.OLDEST:
                cards.sort(key=lambda c: c.acquired_at)
            case InventorySort.SERIES:
                cards.sort(key=lambda c: c.series_name)
            case InventorySort.CHARACTER:
                cards.sort(key=lambda c: c.character_name)
            case InventorySort.RARITY:
                cards.sort(key=lambda c: c.rarity.value, reverse=True)
            case InventorySort.FAVORITES:
                cards.sort(key=lambda c: c.is_favorite, reverse=True)
            case InventorySort.DUPLICATES:
                cards.sort(key=lambda c: c.definition_id)
            case _:
                cards.sort(key=lambda c: c.acquired_at, reverse=True)
        total_count = len(cards)
        total_pages = max(1, (total_count + page_size - 1) // page_size)
        offset = (page - 1) * page_size
        items = tuple(cards[offset : offset + page_size])
        return InventoryPage(
            items=items,
            total_count=total_count,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )

    async def toggle_favorite(
        self,
        player_id: int,
        ownership_id: UUID,
    ) -> bool:
        cards = self._cards.get(player_id, [])
        for card in cards:
            if card.ownership_id == ownership_id:
                new_state = not card.is_favorite
                idx = cards.index(card)
                cards[idx] = InventoryCard(
                    ownership_id=card.ownership_id,
                    definition_id=card.definition_id,
                    print_number=card.print_number,
                    character_name=card.character_name,
                    series_name=card.series_name,
                    rarity=card.rarity,
                    edition=card.edition,
                    variant=card.variant,
                    is_favorite=new_state,
                    acquired_at=card.acquired_at,
                    image_path=card.image_path,
                )
                return new_state
        raise ValueError("card not found")


def make_card(
    ownership_id: UUID | None = None,
    character: str = "Character",
    series: str = "Series",
    rarity: Rarity = Rarity.COMMON,
    favorite: bool = False,
    acquired: datetime | None = None,
) -> InventoryCard:
    return InventoryCard(
        ownership_id=ownership_id or uuid4(),
        definition_id=uuid4(),
        print_number=1,
        character_name=character,
        series_name=series,
        rarity=rarity,
        edition="standard",
        variant="base",
        is_favorite=favorite,
        acquired_at=acquired or datetime.now(UTC),
        image_path="artwork/card.png",
    )


class InventoryServiceTests(unittest.IsolatedAsyncioTestCase):
    def make_service(
        self,
    ) -> tuple[InventoryService, MemoryInventoryQuery]:
        query = MemoryInventoryQuery()
        service = InventoryService(query=query)
        return service, query

    async def test_empty_inventory_returns_empty_page(self) -> None:
        service, _ = self.make_service()
        page = await service.list_cards(100)
        self.assertEqual(page.total_count, 0)
        self.assertEqual(len(page.items), 0)
        self.assertEqual(page.total_pages, 1)

    async def test_returns_all_cards_for_player(self) -> None:
        service, query = self.make_service()
        cards = [make_card(character=f"Char {i}") for i in range(5)]
        for card in cards:
            query.add_card(100, card)

        page = await service.list_cards(100)
        self.assertEqual(page.total_count, 5)
        self.assertEqual(len(page.items), 5)

    async def test_pagination(self) -> None:
        service, query = self.make_service()
        for i in range(25):
            query.add_card(100, make_card(character=f"Char {i}"))

        page1 = await service.list_cards(100, page=1, page_size=10)
        self.assertEqual(len(page1.items), 10)
        self.assertEqual(page1.total_pages, 3)
        self.assertTrue(page1.has_next)
        self.assertFalse(page1.has_previous)

        page2 = await service.list_cards(100, page=2, page_size=10)
        self.assertEqual(len(page2.items), 10)

        page3 = await service.list_cards(100, page=3, page_size=10)
        self.assertEqual(len(page3.items), 5)
        self.assertTrue(page3.has_previous)
        self.assertFalse(page3.has_next)

    async def test_filters_by_rarity(self) -> None:
        service, query = self.make_service()
        query.add_card(100, make_card(rarity=Rarity.COMMON))
        query.add_card(100, make_card(rarity=Rarity.LEGENDARY))
        query.add_card(100, make_card(rarity=Rarity.COMMON))

        page = await service.list_cards(
            100,
            filters=InventoryFilters(rarity=Rarity.COMMON),
        )
        self.assertEqual(page.total_count, 2)

    async def test_filters_by_character_name(self) -> None:
        service, query = self.make_service()
        query.add_card(100, make_card(character="Gojo Satoru"))
        query.add_card(100, make_card(character="Naruto"))
        query.add_card(100, make_card(character="Gojo Satoru"))

        page = await service.list_cards(
            100,
            filters=InventoryFilters(character_name="Gojo"),
        )
        self.assertEqual(page.total_count, 2)

    async def test_filters_favorites_only(self) -> None:
        service, query = self.make_service()
        query.add_card(100, make_card(favorite=True))
        query.add_card(100, make_card(favorite=False))
        query.add_card(100, make_card(favorite=True))

        page = await service.list_cards(
            100,
            filters=InventoryFilters(favorites_only=True),
        )
        self.assertEqual(page.total_count, 2)

    async def test_search_across_name_and_series(self) -> None:
        service, query = self.make_service()
        query.add_card(100, make_card(character="Gojo Satoru", series="Jujutsu Kaisen"))
        query.add_card(100, make_card(character="Naruto Uzumaki", series="Naruto Shippuden"))
        query.add_card(100, make_card(character="Sasuke", series="Naruto"))
        query.add_card(100, make_card(character="Lelouch", series="Code Geass"))

        page = await service.list_cards(
            100,
            filters=InventoryFilters(search="jujutsu"),
        )
        self.assertEqual(page.total_count, 1)

        page = await service.list_cards(
            100,
            filters=InventoryFilters(search="naruto"),
        )
        self.assertEqual(page.total_count, 2)  # one character match, one series match

    async def test_sort_by_rarity(self) -> None:
        service, query = self.make_service()
        query.add_card(100, make_card(rarity=Rarity.COMMON, character="A"))
        query.add_card(100, make_card(rarity=Rarity.LEGENDARY, character="B"))

        page = await service.list_cards(
            100,
            sort=InventorySort.RARITY,
            page_size=10,
        )
        self.assertEqual(page.items[0].rarity, Rarity.LEGENDARY)

    async def test_toggle_favorite(self) -> None:
        service, query = self.make_service()
        ownership_id = uuid4()
        card = make_card(ownership_id=ownership_id, favorite=False)
        query.add_card(100, card)

        new_state = await service.toggle_favorite(100, ownership_id)
        self.assertTrue(new_state)

        new_state = await service.toggle_favorite(100, ownership_id)
        self.assertFalse(new_state)
