from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import joinedload

from larpcard.cards.domain import CardTemplate, Rarity, RenderCard
from larpcard.database.models import (
    CardDefinitionModel,
    CharacterModel,
    DropModel,
    DropSlotModel,
    MarketplaceListingModel,
    OwnedCardModel,
    PlayerModel,
    RewardClaimModel,
    TradeCardModel,
    TradeModel,
    TransactionModel,
)
from larpcard.drops.domain import (
    ClaimReceipt,
    Drop,
    DropExpiredError,
    DropSlot,
    DropSlotStatus,
    SlotAlreadyClaimedError,
    SlotNotFoundError,
)
from larpcard.economy.domain import (
    Balance,
    CurrencyType,
    InsufficientFundsError,
    RewardAlreadyClaimedError,
    RewardClaim,
    RewardType,
    Transaction,
    TransactionType,
)
from larpcard.inventory.domain import (
    InventoryCard,
    InventoryFilters,
    InventoryPage,
    InventorySort,
)
from larpcard.marketplace.domain import (
    Listing,
    ListingFilters,
    ListingPage,
    ListingSort,
    ListingStatus,
)
from larpcard.trade.domain import Trade, TradeCard, TradeCardNotOwnedError, TradeState

_DAILY_REWARD_AMOUNT = 100
_WEEKLY_REWARD_AMOUNT = 500


class SqlAlchemyCardCatalog:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def list_active(self) -> Sequence[CardTemplate]:
        statement = (
            select(CardDefinitionModel)
            .where(CardDefinitionModel.is_active.is_(True))
            .options(joinedload(CardDefinitionModel.character).joinedload(CharacterModel.series))
            .order_by(CardDefinitionModel.id)
        )
        async with self._sessions() as session:
            definitions = (await session.scalars(statement)).unique().all()
        return tuple(_template_from_model(definition) for definition in definitions)


class SqlAlchemyDropRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def create(
        self,
        *,
        creator_id: int,
        guild_id: int | None,
        channel_id: int,
        templates: Sequence[CardTemplate],
        created_at: datetime,
        expires_at: datetime,
    ) -> Drop:
        if not templates:
            raise ValueError("a drop requires at least one card")

        async with self._sessions() as session, session.begin():
            drop_model = DropModel(
                creator_id=creator_id,
                guild_id=guild_id,
                channel_id=channel_id,
                created_at=created_at,
                expires_at=expires_at,
            )
            session.add(drop_model)
            await session.flush()

            definition_ids = {template.id for template in templates}
            locked_definitions = (
                await session.scalars(
                    select(CardDefinitionModel)
                    .where(
                        CardDefinitionModel.id.in_(definition_ids),
                        CardDefinitionModel.is_active.is_(True),
                    )
                    .order_by(CardDefinitionModel.id)
                    .with_for_update()
                )
            ).all()
            definitions_by_id = {definition.id: definition for definition in locked_definitions}
            if definitions_by_id.keys() != definition_ids:
                missing = definition_ids - definitions_by_id.keys()
                raise ValueError(f"active card definitions not found: {sorted(map(str, missing))}")

            slots: list[DropSlot] = []
            for position, template in enumerate(templates):
                definition = definitions_by_id[template.id]
                print_number = definition.next_print_number
                definition.next_print_number += 1
                slot_model = DropSlotModel(
                    drop_id=drop_model.id,
                    definition_id=definition.id,
                    position=position,
                    print_number=print_number,
                )
                session.add(slot_model)
                await session.flush()
                slots.append(
                    DropSlot(
                        id=slot_model.id,
                        position=position,
                        card=RenderCard(
                            template_id=template.id,
                            character_name=template.character_name,
                            series_name=template.series_name,
                            rarity=template.rarity,
                            print_number=print_number,
                            edition=template.edition,
                            variant=template.variant,
                        ),
                        image_path=template.image_path,
                        frame_path=template.frame_path,
                    )
                )

        return Drop(
            id=drop_model.id,
            creator_id=creator_id,
            guild_id=guild_id,
            channel_id=channel_id,
            created_at=created_at,
            expires_at=expires_at,
            slots=tuple(slots),
        )

    async def bind_message(self, drop_id: UUID, message_id: int) -> None:
        async with self._sessions() as session, session.begin():
            drop = await session.get(DropModel, drop_id, with_for_update=True)
            if drop is None:
                raise ValueError(f"drop not found: {drop_id}")
            drop.message_id = message_id

    async def claim(
        self,
        slot_id: UUID,
        claimant_id: int,
        claimed_at: datetime,
    ) -> ClaimReceipt:
        ownership_id = uuid4()

        async with self._sessions() as session, session.begin():
            slot = await session.scalar(
                select(DropSlotModel)
                .where(DropSlotModel.id == slot_id)
                .with_for_update(of=DropSlotModel)
            )
            if slot is None:
                raise SlotNotFoundError(f"drop slot not found: {slot_id}")
            if slot.status is not DropSlotStatus.AVAILABLE:
                raise SlotAlreadyClaimedError(f"drop slot is {slot.status.value}")

            drop = await session.get(DropModel, slot.drop_id)
            if drop is None:
                raise SlotNotFoundError(f"drop not found for slot: {slot_id}")
            if claimed_at >= drop.expires_at:
                raise DropExpiredError("the claim window has expired")

            definition = await session.scalar(
                select(CardDefinitionModel)
                .where(CardDefinitionModel.id == slot.definition_id)
                .options(
                    joinedload(CardDefinitionModel.character).joinedload(CharacterModel.series)
                )
            )
            if definition is None:
                raise SlotNotFoundError(f"card definition not found for slot: {slot_id}")

            await session.execute(
                insert(PlayerModel)
                .values(discord_user_id=claimant_id)
                .on_conflict_do_nothing(index_elements=[PlayerModel.discord_user_id])
            )
            ownership = OwnedCardModel(
                id=ownership_id,
                owner_id=claimant_id,
                definition_id=slot.definition_id,
                print_number=slot.print_number,
                source_drop_slot_id=slot.id,
                acquired_at=claimed_at,
            )
            session.add(ownership)
            slot.status = DropSlotStatus.CLAIMED
            slot.claimed_by = claimant_id
            slot.claimed_at = claimed_at

            character_name = definition.character.name
            print_number = slot.print_number

        return ClaimReceipt(
            ownership_id=ownership_id,
            slot_id=slot_id,
            claimant_id=claimant_id,
            character_name=character_name,
            print_number=print_number,
            claim_code=_short_code(ownership_id),
            claimed_at=claimed_at,
        )


def _template_from_model(definition: CardDefinitionModel) -> CardTemplate:
    return CardTemplate(
        id=definition.id,
        character_name=definition.character.name,
        series_name=definition.character.series.name,
        aliases=tuple(definition.character.aliases),
        image_path=definition.image_path,
        frame_path=definition.frame_path,
        rarity=definition.rarity,
        edition=definition.edition,
        variant=definition.variant,
        tags=tuple(definition.tags),
        release_date=definition.release_date,
        artist=definition.artist,
        drop_weight=definition.drop_weight,
    )


def _short_code(value: UUID, length: int = 6) -> str:
    alphabet = "0123456789abcdefghijklmnopqrstuvwxyz"
    number = value.int
    encoded: list[str] = []
    while number and len(encoded) < length:
        number, remainder = divmod(number, len(alphabet))
        encoded.append(alphabet[remainder])
    return "".join(reversed(encoded)).rjust(length, "0")


class SqlAlchemyBalanceStore:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def get_balance(self, player_id: int) -> Balance:
        async with self._sessions() as session:
            player = await session.get(PlayerModel, player_id)
            if player is None:
                return Balance(coins=0, gems=0, event_tokens=0)
            return Balance(
                coins=player.coins,
                gems=player.gems,
                event_tokens=player.event_tokens,
            )

    async def add_currency(
        self,
        player_id: int,
        currency: CurrencyType,
        amount: int,
    ) -> Balance:
        async with self._sessions() as session, session.begin():
            player = await session.get(PlayerModel, player_id, with_for_update=True)
            if player is None:
                player = PlayerModel(discord_user_id=player_id)
                session.add(player)
                await session.flush()
            _adjust_balance(player, currency, amount)
        return Balance(
            coins=player.coins,
            gems=player.gems,
            event_tokens=player.event_tokens,
        )

    async def remove_currency(
        self,
        player_id: int,
        currency: CurrencyType,
        amount: int,
    ) -> Balance:
        async with self._sessions() as session, session.begin():
            player = await session.get(PlayerModel, player_id, with_for_update=True)
            if player is None:
                raise InsufficientFundsError(currency, amount, 0)
            _adjust_balance(player, currency, -amount)
        return Balance(
            coins=player.coins,
            gems=player.gems,
            event_tokens=player.event_tokens,
        )


class SqlAlchemyTransactionLog:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def record(
        self,
        *,
        player_id: int,
        transaction_type: TransactionType,
        currency: CurrencyType,
        amount: int,
        balance_after: int,
        reference_id: str | None = None,
        description: str | None = None,
    ) -> Transaction:
        async with self._sessions() as session, session.begin():
            model = TransactionModel(
                player_id=player_id,
                transaction_type=transaction_type.value,
                currency=currency.value,
                amount=amount,
                balance_after=balance_after,
                reference_id=reference_id,
                description=description,
            )
            session.add(model)
            await session.flush()
        return Transaction(
            id=model.id,
            player_id=model.player_id,
            transaction_type=TransactionType(model.transaction_type),
            currency=CurrencyType(model.currency),
            amount=model.amount,
            balance_after=model.balance_after,
            reference_id=model.reference_id,
            description=model.description,
            created_at=model.created_at,
        )

    async def list_recent(
        self,
        player_id: int,
        limit: int = 20,
        offset: int = 0,
    ) -> Sequence[Transaction]:
        async with self._sessions() as session:
            models = (
                await session.scalars(
                    select(TransactionModel)
                    .where(TransactionModel.player_id == player_id)
                    .order_by(TransactionModel.created_at.desc())
                    .offset(offset)
                    .limit(limit)
                )
            ).all()
        return [
            Transaction(
                id=model.id,
                player_id=model.player_id,
                transaction_type=TransactionType(model.transaction_type),
                currency=CurrencyType(model.currency),
                amount=model.amount,
                balance_after=model.balance_after,
                reference_id=model.reference_id,
                description=model.description,
                created_at=model.created_at,
            )
            for model in models
        ]


class SqlAlchemyRewardStore:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def claim_reward(
        self,
        player_id: int,
        reward_type: RewardType,
        today: date,
    ) -> RewardClaim:
        async with self._sessions() as session, session.begin():
            existing = await session.scalar(
                select(RewardClaimModel).where(
                    RewardClaimModel.player_id == player_id,
                    RewardClaimModel.reward_type == reward_type.value,
                    RewardClaimModel.claim_date == today,
                )
            )
            if existing is not None:
                raise RewardAlreadyClaimedError(
                    f"{reward_type.value} reward already claimed today"
                )

            last = await session.scalar(
                select(RewardClaimModel)
                .where(
                    RewardClaimModel.player_id == player_id,
                    RewardClaimModel.reward_type == reward_type.value,
                )
                .order_by(RewardClaimModel.claim_date.desc())
                .limit(1)
            )

            streak = 1
            if last is not None:
                expected = last.claim_date
                yesterday = today
                from datetime import timedelta

                yesterday = today - timedelta(days=1)
                if last.claim_date == yesterday:
                    streak = last.streak + 1

            model = RewardClaimModel(
                player_id=player_id,
                reward_type=reward_type.value,
                currency="coins" if reward_type == RewardType.DAILY else "gems",
                amount=_DAILY_REWARD_AMOUNT
                if reward_type == RewardType.DAILY
                else _WEEKLY_REWARD_AMOUNT,
                streak=streak,
                claim_date=today,
            )
            session.add(model)
            await session.flush()

        return RewardClaim(
            id=model.id,
            player_id=model.player_id,
            reward_type=RewardType(model.reward_type),
            currency=CurrencyType(model.currency),
            amount=model.amount,
            streak=model.streak,
            claimed_at=model.created_at,
        )

    async def last_claim(
        self,
        player_id: int,
        reward_type: RewardType,
    ) -> RewardClaim | None:
        async with self._sessions() as session:
            model = await session.scalar(
                select(RewardClaimModel)
                .where(
                    RewardClaimModel.player_id == player_id,
                    RewardClaimModel.reward_type == reward_type.value,
                )
                .order_by(RewardClaimModel.created_at.desc())
                .limit(1)
            )
        if model is None:
            return None
        return RewardClaim(
            id=model.id,
            player_id=model.player_id,
            reward_type=RewardType(model.reward_type),
            currency=CurrencyType(model.currency),
            amount=model.amount,
            streak=model.streak,
            claimed_at=model.created_at,
        )


class SqlAlchemyInventoryQuery:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def query(
        self,
        player_id: int,
        *,
        filters: InventoryFilters,
        sort: InventorySort,
        page: int = 1,
        page_size: int = 20,
    ) -> InventoryPage:
        async with self._sessions() as session:
            base = (
                select(OwnedCardModel)
                .where(OwnedCardModel.owner_id == player_id)
                .options(
                    joinedload(OwnedCardModel.definition)
                    .joinedload(CardDefinitionModel.character)
                    .joinedload(CharacterModel.series)
                )
            )

            if filters.favorites_only:
                base = base.where(OwnedCardModel.is_favorite.is_(True))
            if filters.rarity is not None:
                base = base.where(CardDefinitionModel.rarity == filters.rarity)
            if filters.character_name:
                base = base.where(CharacterModel.name.ilike(filters.character_name))
            if filters.series_name:
                base = base.where(SeriesModel.name.ilike(filters.series_name))
            if filters.search:
                pattern = f"%{filters.search}%"
                base = base.where(
                    CharacterModel.name.ilike(pattern)
                    | SeriesModel.name.ilike(pattern)
                )

            count_stmt = base.with_only_columns(
                func.count(OwnedCardModel.id),
                maintain_column_froms=False,
            )
            total_count = (await session.scalar(count_stmt)) or 0

            order: Any
            match sort:
                case InventorySort.NEWEST:
                    order = OwnedCardModel.acquired_at.desc()
                case InventorySort.OLDEST:
                    order = OwnedCardModel.acquired_at.asc()
                case InventorySort.SERIES:
                    order = SeriesModel.name.asc()
                case InventorySort.CHARACTER:
                    order = CharacterModel.name.asc()
                case InventorySort.RARITY:
                    order = CardDefinitionModel.rarity.desc()
                case InventorySort.FAVORITES:
                    order = OwnedCardModel.is_favorite.desc()
                case InventorySort.DUPLICATES:
                    order = OwnedCardModel.definition_id.asc()
                case _:
                    order = OwnedCardModel.acquired_at.desc()

            offset = (page - 1) * page_size
            models = (
                (
                    await session.scalars(
                        base.order_by(order)
                        .offset(offset)
                        .limit(page_size)
                    )
                )
                .unique()
                .all()
            )

        total_pages = max(1, (total_count + page_size - 1) // page_size)
        return InventoryPage(
            items=tuple(_inventory_card_from_model(m) for m in models),
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
        async with self._sessions() as session, session.begin():
            card = await session.scalar(
                select(OwnedCardModel).where(
                    OwnedCardModel.id == ownership_id,
                    OwnedCardModel.owner_id == player_id,
                )
            )
            if card is None:
                raise ValueError(f"owned card not found: {ownership_id}")
            card.is_favorite = not card.is_favorite
            return card.is_favorite


class SqlAlchemyMarketplaceRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

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
        async with self._sessions() as session, session.begin():
            model = MarketplaceListingModel(
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
                status=ListingStatus.ACTIVE.value,
                image_path=image_path,
                created_at=created_at,
            )
            session.add(model)
            await session.flush()
        return _listing_from_model(model)

    async def get_active_listing(self, listing_id: UUID) -> Listing | None:
        async with self._sessions() as session:
            model = await session.scalar(
                select(MarketplaceListingModel).where(
                    MarketplaceListingModel.id == listing_id,
                    MarketplaceListingModel.status == ListingStatus.ACTIVE.value,
                )
            )
        if model is None:
            return None
        return _listing_from_model(model)

    async def get_listing(self, listing_id: UUID) -> Listing | None:
        async with self._sessions() as session:
            model = await session.get(MarketplaceListingModel, listing_id)
        if model is None:
            return None
        return _listing_from_model(model)

    async def mark_sold(
        self,
        listing_id: UUID,
        buyer_id: int,
        sold_at: datetime,
    ) -> None:
        async with self._sessions() as session, session.begin():
            model = await session.get(
                MarketplaceListingModel, listing_id, with_for_update=True
            )
            if model is not None:
                model.status = ListingStatus.SOLD.value
                model.buyer_id = buyer_id
                model.sold_at = sold_at

    async def cancel_listing(self, listing_id: UUID) -> None:
        async with self._sessions() as session, session.begin():
            model = await session.get(
                MarketplaceListingModel, listing_id, with_for_update=True
            )
            if model is not None:
                model.status = ListingStatus.CANCELLED.value

    async def query(
        self,
        *,
        filters: ListingFilters,
        sort: ListingSort,
        page: int,
        page_size: int,
    ) -> ListingPage:
        async with self._sessions() as session:
            base = select(MarketplaceListingModel).where(
                MarketplaceListingModel.status == ListingStatus.ACTIVE.value
            )

            if filters.rarity is not None:
                base = base.where(
                    MarketplaceListingModel.rarity == filters.rarity.value
                )
            if filters.series_name:
                base = base.where(
                    MarketplaceListingModel.series_name.ilike(filters.series_name)
                )
            if filters.character_name:
                base = base.where(
                    MarketplaceListingModel.character_name.ilike(filters.character_name)
                )
            if filters.seller_id is not None:
                base = base.where(
                    MarketplaceListingModel.seller_id == filters.seller_id
                )
            if filters.min_price is not None:
                base = base.where(
                    MarketplaceListingModel.price >= filters.min_price
                )
            if filters.max_price is not None:
                base = base.where(
                    MarketplaceListingModel.price <= filters.max_price
                )
            if filters.search:
                pattern = f"%{filters.search}%"
                base = base.where(
                    MarketplaceListingModel.character_name.ilike(pattern)
                    | MarketplaceListingModel.series_name.ilike(pattern)
                )

            count_stmt = base.with_only_columns(
                func.count(MarketplaceListingModel.id),
                maintain_column_froms=False,
            )
            total_count = (await session.scalar(count_stmt)) or 0

            order: Any
            match sort:
                case ListingSort.NEWEST:
                    order = MarketplaceListingModel.created_at.desc()
                case ListingSort.OLDEST:
                    order = MarketplaceListingModel.created_at.asc()
                case ListingSort.PRICE_ASC:
                    order = MarketplaceListingModel.price.asc()
                case ListingSort.PRICE_DESC:
                    order = MarketplaceListingModel.price.desc()
                case ListingSort.RARITY:
                    order = MarketplaceListingModel.rarity.desc()
                case _:
                    order = MarketplaceListingModel.created_at.desc()

            offset = (page - 1) * page_size
            models = (
                await session.scalars(
                    base.order_by(order).offset(offset).limit(page_size)
                )
            ).all()

        total_pages = max(1, (total_count + page_size - 1) // page_size)
        return ListingPage(
            items=tuple(_listing_from_model(m) for m in models),
            total_count=total_count,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )

    async def count_active_by_ownership(
        self,
        ownership_id: UUID,
    ) -> int:
        async with self._sessions() as session:
            count = await session.scalar(
                select(func.count(MarketplaceListingModel.id)).where(
                    MarketplaceListingModel.ownership_id == ownership_id,
                    MarketplaceListingModel.status == ListingStatus.ACTIVE.value,
                )
            )
            return count or 0


class SqlAlchemyTradeRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def create(
        self,
        trade_id: UUID,
        player1_id: int,
        player2_id: int,
    ) -> Trade:
        async with self._sessions() as session, session.begin():
            model = TradeModel(
                id=trade_id,
                player1_id=player1_id,
                player2_id=player2_id,
                state=TradeState.PENDING.value,
            )
            session.add(model)
            await session.flush()
        return _trade_from_model(model)

    async def get(self, trade_id: UUID) -> Trade | None:
        async with self._sessions() as session:
            model = await session.scalar(
                select(TradeModel)
                .where(TradeModel.id == trade_id)
                .options(
                    joinedload(TradeModel.player1_card_slots)
                )
            )
        if model is None:
            return None
        return _trade_from_model(model)

    async def add_cards(
        self,
        trade_id: UUID,
        player_id: int,
        ownership_ids: list[UUID],
    ) -> Trade:
        async with self._sessions() as session, session.begin():
            # Verify all cards are owned by the player
            cards = (
                await session.scalars(
                    select(OwnedCardModel)
                    .where(
                        OwnedCardModel.id.in_(ownership_ids),
                        OwnedCardModel.owner_id == player_id,
                    )
                    .options(
                        joinedload(OwnedCardModel.definition)
                        .joinedload(CardDefinitionModel.character)
                        .joinedload(CharacterModel.series)
                    )
                )
            ).all()

            if len(cards) != len(ownership_ids):
                found = {c.id for c in cards}
                missing = set(ownership_ids) - found
                raise TradeCardNotOwnedError(
                    f"cards not owned: {sorted(map(str, missing))}"
                )

            # Remove existing cards for this player and trade
            existing = await session.scalars(
                select(TradeCardModel).where(
                    TradeCardModel.trade_id == trade_id,
                    TradeCardModel.owner_id == player_id,
                )
            )
            for ec in existing:
                await session.delete(ec)

            # Add new cards
            for card in cards:
                definition = card.definition
                character = definition.character
                slot = TradeCardModel(
                    trade_id=trade_id,
                    owner_id=player_id,
                    ownership_id=card.id,
                    character_name=character.name,
                    series_name=character.series.name,
                    rarity=definition.rarity.value,
                    print_number=card.print_number,
                    edition=definition.edition,
                    variant=definition.variant,
                    image_path=definition.image_path,
                )
                session.add(slot)

            # Reset confirmation state when cards change
            trade_model = await session.get(TradeModel, trade_id)
            if trade_model is not None:
                trade_model.state = TradeState.PENDING.value

            await session.flush()

        return await self.get(trade_id)  # type: ignore[return-value]

    async def set_state(
        self,
        trade_id: UUID,
        state: str,
    ) -> None:
        async with self._sessions() as session, session.begin():
            model = await session.get(TradeModel, trade_id)
            if model is not None:
                model.state = state

    async def complete(self, trade_id: UUID) -> None:
        async with self._sessions() as session, session.begin():
            model = await session.get(TradeModel, trade_id)
            if model is None:
                return

            from datetime import UTC, datetime

            now = datetime.now(UTC)

            # Load card slots
            slots = (
                await session.scalars(
                    select(TradeCardModel).where(
                        TradeCardModel.trade_id == trade_id
                    )
                )
            ).all()

            # Transfer ownership
            for slot in slots:
                owner_id = slot.owner_id
                # Find the other player
                if owner_id == model.player1_id:
                    new_owner_id = model.player2_id
                else:
                    new_owner_id = model.player1_id

                owned = await session.get(OwnedCardModel, slot.ownership_id)
                if owned is not None:
                    owned.owner_id = new_owner_id

            model.state = TradeState.COMPLETED.value
            model.completed_at = now

    async def cancel(self, trade_id: UUID) -> None:
        async with self._sessions() as session, session.begin():
            model = await session.get(TradeModel, trade_id)
            if model is not None:
                model.state = TradeState.CANCELLED.value


def _listing_from_model(model: MarketplaceListingModel) -> Listing:
    return Listing(
        id=model.id,
        seller_id=model.seller_id,
        ownership_id=model.ownership_id,
        definition_id=model.definition_id,
        character_name=model.character_name,
        series_name=model.series_name,
        rarity=Rarity(model.rarity),
        print_number=model.print_number,
        edition=model.edition,
        variant=model.variant,
        price=model.price,
        status=ListingStatus(model.status),
        created_at=model.created_at,
        sold_at=model.sold_at,
        buyer_id=model.buyer_id,
        image_path=model.image_path,
    )


def _trade_card_from_model(model: TradeCardModel) -> TradeCard:
    return TradeCard(
        ownership_id=model.ownership_id,
        definition_id=model.ownership_id,
        character_name=model.character_name,
        series_name=model.series_name,
        rarity=Rarity(model.rarity),
        print_number=model.print_number,
        edition=model.edition,
        variant=model.variant,
        image_path=model.image_path,
    )


def _trade_from_model(model: TradeModel) -> Trade:
    p1_cards: list[TradeCard] = []
    p2_cards: list[TradeCard] = []
    for slot in model.player1_card_slots:
        card = _trade_card_from_model(slot)
        if slot.owner_id == model.player1_id:
            p1_cards.append(card)
        else:
            p2_cards.append(card)
    return Trade(
        id=model.id,
        player1_id=model.player1_id,
        player2_id=model.player2_id,
        state=TradeState(model.state),
        player1_cards=tuple(p1_cards),
        player2_cards=tuple(p2_cards),
        created_at=model.created_at,
        completed_at=model.completed_at,
    )


def _inventory_card_from_model(model: OwnedCardModel) -> InventoryCard:
    definition = model.definition
    character = definition.character
    return InventoryCard(
        ownership_id=model.id,
        definition_id=definition.id,
        print_number=model.print_number,
        character_name=character.name,
        series_name=character.series.name,
        rarity=definition.rarity,
        edition=definition.edition,
        variant=definition.variant,
        is_favorite=model.is_favorite,
        acquired_at=model.acquired_at,
        image_path=definition.image_path,
    )


def _adjust_balance(player: PlayerModel, currency: CurrencyType, amount: int) -> None:
    match currency:
        case CurrencyType.COINS:
            player.coins += amount
        case CurrencyType.GEMS:
            player.gems += amount
        case CurrencyType.EVENT_TOKENS:
            player.event_tokens += amount
