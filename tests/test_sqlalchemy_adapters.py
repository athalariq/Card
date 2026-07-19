"""SQLite-backed smoke tests for the SQLAlchemy repository adapters.

These run against a throwaway in-memory database so the adapter SQL — joins,
filters, stake counters, and ownership transfers — is actually exercised
without needing PostgreSQL or Redis.
"""

from __future__ import annotations

import unittest
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from larpcard.cards.domain import Rarity
from larpcard.database.base import Base
from larpcard.database.models import (
    CardDefinitionModel,
    CharacterModel,
    DropModel,
    DropSlotModel,
    MarketplaceListingModel,
    OwnedCardModel,
    PlayerModel,
    SeriesModel,
)
from larpcard.database.repositories import (
    SqlAlchemyBalanceStore,
    SqlAlchemyInventoryQuery,
    SqlAlchemyMarketplaceRepository,
    SqlAlchemyRewardStore,
    SqlAlchemyTradeRepository,
    SqlAlchemyTransactionLog,
)
from larpcard.drops.domain import DropSlotStatus
from larpcard.economy.domain import (
    CurrencyType,
    InsufficientFundsError,
    RewardAlreadyClaimedError,
    RewardType,
    TransactionType,
)
from larpcard.economy.service import EconomyService
from larpcard.inventory.domain import InventoryFilters, InventorySort
from larpcard.marketplace.domain import (
    ListingError,
    ListingFilters,
    ListingStatus,
    NotOwnerError,
)
from larpcard.marketplace.service import MarketplaceService
from larpcard.trade.domain import (
    TradeCardNotOwnedError,
    TradeInvalidStateError,
    TradeState,
)
from larpcard.trade.service import TradeService

SELLER = 100
BUYER = 200


class World:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions
        self.gojo_definition_id: UUID
        self.jinwoo_definition_id: UUID
        self.gojo_card1: UUID
        self.gojo_card2: UUID
        self.jinwoo_card1: UUID  # owned by SELLER, favorited
        self.jinwoo_card2: UUID  # owned by BUYER


async def _make_sessions() -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _seed_world(sessions: async_sessionmaker[AsyncSession]) -> World:
    world = World(sessions)
    now = datetime.now(UTC)
    async with sessions() as session, session.begin():
        session.add_all(
            [
                PlayerModel(discord_user_id=SELLER),
                PlayerModel(discord_user_id=BUYER),
            ]
        )
        jjk = SeriesModel(name="Jujutsu Kaisen", slug="jujutsu-kaisen")
        solo = SeriesModel(name="Solo Leveling", slug="solo-leveling")
        session.add_all([jjk, solo])
        await session.flush()

        gojo = CharacterModel(series_id=jjk.id, name="Gojo Satoru", aliases=[])
        jinwoo = CharacterModel(series_id=solo.id, name="Sung Jinwoo", aliases=[])
        session.add_all([gojo, jinwoo])
        await session.flush()

        gojo_def = CardDefinitionModel(
            character_id=gojo.id,
            image_path="artwork/gojo.png",
            rarity=Rarity.COMMON,
            edition="standard",
            variant="base",
        )
        jinwoo_def = CardDefinitionModel(
            character_id=jinwoo.id,
            image_path="artwork/jinwoo.png",
            frame_path="frames/legendary.png",
            rarity=Rarity.LEGENDARY,
            edition="standard",
            variant="base",
        )
        session.add_all([gojo_def, jinwoo_def])
        await session.flush()

        drop = DropModel(
            creator_id=SELLER,
            channel_id=777,
            created_at=now - timedelta(minutes=5),
            expires_at=now + timedelta(minutes=5),
        )
        session.add(drop)
        await session.flush()
        position_counter = [0]

        async def add_owned(
            definition: CardDefinitionModel,
            print_number: int,
            owner_id: int,
            favorite: bool,
        ) -> UUID:
            slot = DropSlotModel(
                drop_id=drop.id,
                definition_id=definition.id,
                position=position_counter[0],
                print_number=print_number,
                status=DropSlotStatus.CLAIMED,
                claimed_by=owner_id,
                claimed_at=now,
            )
            position_counter[0] += 1
            session.add(slot)
            await session.flush()
            owned = OwnedCardModel(
                owner_id=owner_id,
                definition_id=definition.id,
                print_number=print_number,
                source_drop_slot_id=slot.id,
                is_favorite=favorite,
                acquired_at=now - timedelta(days=print_number),
            )
            session.add(owned)
            await session.flush()
            return owned.id

        world.gojo_definition_id = gojo_def.id
        world.jinwoo_definition_id = jinwoo_def.id
        world.gojo_card1 = await add_owned(gojo_def, 1, SELLER, False)
        world.gojo_card2 = await add_owned(gojo_def, 2, SELLER, False)
        world.jinwoo_card1 = await add_owned(jinwoo_def, 1, SELLER, True)
        world.jinwoo_card2 = await add_owned(jinwoo_def, 2, BUYER, False)
    return world


class SqlAlchemyAdapterTests(unittest.IsolatedAsyncioTestCase):
    engine: AsyncEngine
    sessions: async_sessionmaker[AsyncSession]
    world: World

    async def asyncSetUp(self) -> None:
        self.engine, self.sessions = await _make_sessions()
        self.world = await _seed_world(self.sessions)

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()

    # -- balances & transactions -------------------------------------------

    async def test_balance_lifecycle(self) -> None:
        store = SqlAlchemyBalanceStore(self.sessions)
        self.assertEqual(
            (await store.get_balance(SELLER)).coins,
            0,
        )
        balance = await store.add_currency(SELLER, CurrencyType.COINS, 250)
        self.assertEqual(balance.coins, 250)
        balance = await store.remove_currency(SELLER, CurrencyType.COINS, 100)
        self.assertEqual(balance.coins, 150)

        # overdraw rejection lives in the service layer
        economy = EconomyService(
            balances=store,
            transactions=SqlAlchemyTransactionLog(self.sessions),
            rewards=SqlAlchemyRewardStore(self.sessions),
        )
        with self.assertRaises(InsufficientFundsError):
            await economy.remove_currency(SELLER, CurrencyType.COINS, 10_000)

    async def test_add_currency_creates_player_row(self) -> None:
        store = SqlAlchemyBalanceStore(self.sessions)
        balance = await store.add_currency(999, CurrencyType.GEMS, 5)
        self.assertEqual(balance.gems, 5)
        self.assertEqual((await store.get_balance(999)).gems, 5)

    async def test_transaction_log_records_and_lists(self) -> None:
        log = SqlAlchemyTransactionLog(self.sessions)
        await log.record(
            player_id=SELLER,
            transaction_type=TransactionType.DAILY_REWARD,
            currency=CurrencyType.COINS,
            amount=100,
            balance_after=100,
            description="daily reward (streak: 1)",
        )
        await log.record(
            player_id=SELLER,
            transaction_type=TransactionType.MARKETPLACE_SALE,
            currency=CurrencyType.COINS,
            amount=4750,
            balance_after=4850,
            reference_id="listing-1",
        )
        recent = await log.list_recent(SELLER)
        self.assertEqual(len(recent), 2)
        self.assertEqual(recent[0].transaction_type, TransactionType.MARKETPLACE_SALE)
        self.assertEqual(recent[0].reference_id, "listing-1")
        self.assertEqual(recent[1].description, "daily reward (streak: 1)")

    # -- reward store -------------------------------------------------------

    async def test_reward_claim_date_and_duplicate(self) -> None:
        store = SqlAlchemyRewardStore(self.sessions)
        today = date.today()
        claim = await store.claim_reward(SELLER, RewardType.DAILY, today)
        self.assertEqual(claim.claim_date, today)
        self.assertEqual(claim.streak, 1)
        with self.assertRaises(RewardAlreadyClaimedError):
            await store.claim_reward(SELLER, RewardType.DAILY, today)

    async def test_daily_streak_continues_across_days(self) -> None:
        store = SqlAlchemyRewardStore(self.sessions)
        today = date.today()
        await store.claim_reward(SELLER, RewardType.DAILY, today - timedelta(days=1))
        claim = await store.claim_reward(SELLER, RewardType.DAILY, today)
        self.assertEqual(claim.streak, 2)

    async def test_weekly_streak_survives_grace_window(self) -> None:
        store = SqlAlchemyRewardStore(self.sessions)
        today = date.today()
        await store.claim_reward(SELLER, RewardType.WEEKLY, today - timedelta(days=9))
        claim = await store.claim_reward(SELLER, RewardType.WEEKLY, today)
        self.assertEqual(claim.streak, 2)

    async def test_weekly_streak_resets_after_long_gap(self) -> None:
        store = SqlAlchemyRewardStore(self.sessions)
        today = date.today()
        await store.claim_reward(SELLER, RewardType.WEEKLY, today - timedelta(days=20))
        claim = await store.claim_reward(SELLER, RewardType.WEEKLY, today)
        self.assertEqual(claim.streak, 1)

    async def test_last_claim_returns_none_for_new_player(self) -> None:
        store = SqlAlchemyRewardStore(self.sessions)
        self.assertIsNone(await store.last_claim(SELLER, RewardType.DAILY))

    # -- inventory ----------------------------------------------------------

    async def test_inventory_lists_owned_cards(self) -> None:
        query = SqlAlchemyInventoryQuery(self.sessions)
        page = await query.query(
            SELLER,
            filters=InventoryFilters(),
            sort=InventorySort.NEWEST,
            page_size=20,
        )
        self.assertEqual(page.total_count, 3)
        names = {card.character_name for card in page.items}
        self.assertEqual(names, {"Gojo Satoru", "Sung Jinwoo"})

    async def test_inventory_series_filter_uses_join(self) -> None:
        query = SqlAlchemyInventoryQuery(self.sessions)
        page = await query.query(
            SELLER,
            filters=InventoryFilters(series_name="%solo%"),
            sort=InventorySort.NEWEST,
            page_size=20,
        )
        self.assertEqual(page.total_count, 1)
        self.assertEqual(page.items[0].series_name, "Solo Leveling")

    async def test_inventory_character_and_search_filters(self) -> None:
        query = SqlAlchemyInventoryQuery(self.sessions)
        by_character = await query.query(
            SELLER,
            filters=InventoryFilters(character_name="%gojo%"),
            sort=InventorySort.NEWEST,
            page_size=20,
        )
        self.assertEqual(by_character.total_count, 2)
        by_search = await query.query(
            SELLER,
            filters=InventoryFilters(search="jinwoo"),
            sort=InventorySort.NEWEST,
            page_size=20,
        )
        self.assertEqual(by_search.total_count, 1)
        self.assertEqual(by_search.items[0].rarity, Rarity.LEGENDARY)

    async def test_inventory_rarity_and_favorite_filters(self) -> None:
        query = SqlAlchemyInventoryQuery(self.sessions)
        legendary = await query.query(
            SELLER,
            filters=InventoryFilters(rarity=Rarity.LEGENDARY),
            sort=InventorySort.NEWEST,
            page_size=20,
        )
        self.assertEqual(legendary.total_count, 1)
        favorites = await query.query(
            SELLER,
            filters=InventoryFilters(favorites_only=True),
            sort=InventorySort.NEWEST,
            page_size=20,
        )
        self.assertEqual(favorites.total_count, 1)
        self.assertTrue(favorites.items[0].is_favorite)

    async def test_inventory_rarity_sort_and_pagination(self) -> None:
        query = SqlAlchemyInventoryQuery(self.sessions)
        page = await query.query(
            SELLER,
            filters=InventoryFilters(),
            sort=InventorySort.RARITY,
            page=1,
            page_size=2,
        )
        self.assertEqual(page.total_pages, 2)
        self.assertEqual(len(page.items), 2)
        self.assertEqual(page.items[0].rarity, Rarity.LEGENDARY)

    async def test_inventory_frame_path_mapping(self) -> None:
        query = SqlAlchemyInventoryQuery(self.sessions)
        page = await query.query(
            SELLER,
            filters=InventoryFilters(rarity=Rarity.LEGENDARY),
            sort=InventorySort.NEWEST,
            page_size=20,
        )
        self.assertEqual(page.items[0].frame_path, "frames/legendary.png")
        common = await query.query(
            SELLER,
            filters=InventoryFilters(rarity=Rarity.COMMON),
            sort=InventorySort.NEWEST,
            page=1,
            page_size=1,
        )
        self.assertIsNone(common.items[0].frame_path)

    async def test_toggle_favorite(self) -> None:
        query = SqlAlchemyInventoryQuery(self.sessions)
        new_state = await query.toggle_favorite(SELLER, self.world.gojo_card1)
        self.assertTrue(new_state)
        self.assertFalse(await query.toggle_favorite(SELLER, self.world.gojo_card1))
        with self.assertRaises(ValueError):
            await query.toggle_favorite(SELLER, uuid4())

    # -- marketplace --------------------------------------------------------

    def _marketplace(self) -> MarketplaceService:
        economy = EconomyService(
            balances=SqlAlchemyBalanceStore(self.sessions),
            transactions=SqlAlchemyTransactionLog(self.sessions),
            rewards=SqlAlchemyRewardStore(self.sessions),
        )
        return MarketplaceService(
            repository=SqlAlchemyMarketplaceRepository(self.sessions),
            economy=economy,
            marketplace_fee_percent=5,
        )

    async def test_buy_flow_transfers_coins_and_card(self) -> None:
        marketplace = self._marketplace()
        balances = SqlAlchemyBalanceStore(self.sessions)
        await balances.add_currency(BUYER, CurrencyType.COINS, 10_000)

        listing = await marketplace.list_card(
            seller_id=SELLER,
            ownership_id=self.world.jinwoo_card1,
            definition_id=self.world.jinwoo_definition_id,
            character_name="Sung Jinwoo",
            series_name="Solo Leveling",
            rarity=Rarity.LEGENDARY.value,
            print_number=1,
            edition="standard",
            variant="base",
            price=5_000,
            image_path="artwork/jinwoo.png",
        )
        self.assertEqual(listing.status, ListingStatus.ACTIVE)
        self.assertEqual(listing.frame_path, "frames/legendary.png")

        with self.assertRaises(ListingError):
            await marketplace.list_card(
                seller_id=SELLER,
                ownership_id=self.world.jinwoo_card1,
                definition_id=self.world.jinwoo_definition_id,
                character_name="Sung Jinwoo",
                series_name="Solo Leveling",
                rarity=Rarity.LEGENDARY.value,
                print_number=1,
                edition="standard",
                variant="base",
                price=5_000,
                image_path="artwork/jinwoo.png",
            )

        sold = await marketplace.buy_card(listing.id, buyer_id=BUYER)
        self.assertEqual(sold.status, ListingStatus.SOLD)

        seller_balance = await balances.get_balance(SELLER)
        buyer_balance = await balances.get_balance(BUYER)
        self.assertEqual(seller_balance.coins, 4_750)
        self.assertEqual(buyer_balance.coins, 5_000)

        # the critical part: the buyer now owns the physical card
        async with self.sessions() as session:
            owned = await session.get(OwnedCardModel, self.world.jinwoo_card1)
            assert owned is not None
            self.assertEqual(owned.owner_id, BUYER)
            self.assertFalse(owned.is_favorite)

        # and the seller lost it while the favorite flag did not leak
        inventory = SqlAlchemyInventoryQuery(self.sessions)
        seller_page = await inventory.query(
            SELLER,
            filters=InventoryFilters(),
            sort=InventorySort.NEWEST,
            page_size=20,
        )
        self.assertEqual(seller_page.total_count, 2)
        buyer_page = await inventory.query(
            BUYER,
            filters=InventoryFilters(),
            sort=InventorySort.NEWEST,
            page_size=20,
        )
        self.assertEqual(buyer_page.total_count, 2)

    async def test_marketplace_search_and_seller_filter(self) -> None:
        marketplace = self._marketplace()
        await marketplace.list_card(
            seller_id=SELLER,
            ownership_id=self.world.gojo_card1,
            definition_id=self.world.gojo_definition_id,
            character_name="Gojo Satoru",
            series_name="Jujutsu Kaisen",
            rarity=Rarity.COMMON.value,
            print_number=1,
            edition="standard",
            variant="base",
            price=100,
            image_path="artwork/gojo.png",
        )
        page = await marketplace.search(
            filters=ListingFilters(seller_id=SELLER, max_price=150),
        )
        self.assertEqual(page.total_count, 1)
        self.assertEqual(page.items[0].price, 100)
        empty = await marketplace.search(
            filters=ListingFilters(rarity=Rarity.LEGENDARY),
        )
        self.assertEqual(empty.total_count, 0)

    async def test_cancel_listing_validates_owner(self) -> None:
        marketplace = self._marketplace()
        listing = await marketplace.list_card(
            seller_id=SELLER,
            ownership_id=self.world.gojo_card2,
            definition_id=self.world.gojo_definition_id,
            character_name="Gojo Satoru",
            series_name="Jujutsu Kaisen",
            rarity=Rarity.COMMON.value,
            print_number=2,
            edition="standard",
            variant="base",
            price=100,
            image_path="artwork/gojo.png",
        )
        with self.assertRaises(NotOwnerError):
            await marketplace.cancel_listing(listing.id, BUYER)
        await marketplace.cancel_listing(listing.id, SELLER)
        async with self.sessions() as session:
            model = await session.get(MarketplaceListingModel, listing.id)
            assert model is not None
            self.assertEqual(model.status, ListingStatus.CANCELLED.value)

    # -- trades -------------------------------------------------------------

    async def test_trade_flow_swaps_cards(self) -> None:
        repository = SqlAlchemyTradeRepository(self.sessions)
        trades = TradeService(repository=repository)
        inventory = SqlAlchemyInventoryQuery(self.sessions)

        trade = await trades.initiate(SELLER, BUYER)
        self.assertEqual(trade.state, TradeState.PENDING)

        await trades.add_cards(trade.id, SELLER, [self.world.jinwoo_card1])
        with self.assertRaises(TradeCardNotOwnedError):
            # the buyer cannot offer the seller's cards
            await trades.add_cards(trade.id, BUYER, [self.world.gojo_card1])
        await trades.add_cards(trade.id, BUYER, [self.world.jinwoo_card2])

        current = await trades.get_trade(trade.id)
        self.assertEqual(len(current.cards_for(SELLER)), 1)
        self.assertEqual(len(current.cards_for(BUYER)), 1)
        self.assertEqual(
            current.cards_for(SELLER)[0].character_name,
            "Sung Jinwoo",
        )

        await trades.confirm(trade.id, SELLER)
        # editing an offer after confirming resets the trade back to pending
        await trades.add_cards(trade.id, SELLER, [self.world.jinwoo_card1])
        current = await trades.get_trade(trade.id)
        self.assertEqual(current.state, TradeState.PENDING)

        await trades.confirm(trade.id, SELLER)
        result = await trades.confirm(trade.id, BUYER)
        self.assertEqual(result.state, TradeState.COMPLETED)

        async with self.sessions() as session:
            sold_card = await session.get(OwnedCardModel, self.world.jinwoo_card1)
            got_card = await session.get(OwnedCardModel, self.world.jinwoo_card2)
            assert sold_card is not None
            assert got_card is not None
            self.assertEqual(sold_card.owner_id, BUYER)
            self.assertFalse(sold_card.is_favorite)
            self.assertEqual(got_card.owner_id, SELLER)

        seller_page = await inventory.query(
            SELLER,
            filters=InventoryFilters(),
            sort=InventorySort.NEWEST,
            page_size=20,
        )
        self.assertEqual(seller_page.total_count, 3)  # 2 gojo + traded jinwoo #2

        with self.assertRaises(TradeInvalidStateError):
            await trades.add_cards(trade.id, SELLER, [self.world.gojo_card1])

    async def test_trade_cancel_blocks_modifications(self) -> None:
        repository = SqlAlchemyTradeRepository(self.sessions)
        trades = TradeService(repository=repository)
        trade = await trades.initiate(SELLER, BUYER)
        await trades.cancel(trade.id, BUYER)
        cancelled = await trades.get_trade(trade.id)
        self.assertEqual(cancelled.state, TradeState.CANCELLED)
        self.assertFalse(cancelled.is_active)
        with self.assertRaises(TradeInvalidStateError):
            await trades.add_cards(trade.id, SELLER, [self.world.gojo_card1])
