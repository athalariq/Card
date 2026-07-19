from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from larpcard.cards.domain import Rarity
from larpcard.database.base import Base
from larpcard.drops.domain import DropSlotStatus
from larpcard.marketplace.domain import ListingStatus


def enum_values(enum_type: type[StrEnum]) -> list[str]:
    return [member.value for member in enum_type]


class DropLifecycleStatus(StrEnum):
    ACTIVE = "active"
    CLOSED = "closed"


class SeriesModel(Base):
    __tablename__ = "series"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    slug: Mapped[str] = mapped_column(String(180), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    characters: Mapped[list[CharacterModel]] = relationship(back_populates="series")


class CharacterModel(Base):
    __tablename__ = "characters"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    series_id: Mapped[UUID] = mapped_column(
        ForeignKey("series.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    aliases: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    series: Mapped[SeriesModel] = relationship(back_populates="characters")
    card_definitions: Mapped[list[CardDefinitionModel]] = relationship(back_populates="character")

    __table_args__ = (UniqueConstraint("series_id", "name"),)


class CardDefinitionModel(Base):
    __tablename__ = "card_definitions"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    character_id: Mapped[UUID] = mapped_column(
        ForeignKey("characters.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    image_path: Mapped[str] = mapped_column(Text, nullable=False)
    frame_path: Mapped[str | None] = mapped_column(Text)
    rarity: Mapped[Rarity] = mapped_column(
        Enum(
            Rarity,
            values_callable=enum_values,
            native_enum=False,
            length=32,
            name="card_rarity",
        ),
        nullable=False,
        index=True,
    )
    edition: Mapped[str] = mapped_column(String(80), nullable=False, default="standard")
    variant: Mapped[str] = mapped_column(String(80), nullable=False, default="base")
    tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    release_date: Mapped[date | None] = mapped_column(Date)
    artist: Mapped[str | None] = mapped_column(String(160))
    drop_weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    next_print_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    character: Mapped[CharacterModel] = relationship(back_populates="card_definitions")
    drop_slots: Mapped[list[DropSlotModel]] = relationship(back_populates="definition")
    owned_cards: Mapped[list[OwnedCardModel]] = relationship(back_populates="definition")

    __table_args__ = (
        CheckConstraint("drop_weight > 0", name="positive_drop_weight"),
        CheckConstraint("next_print_number > 0", name="positive_next_print_number"),
        UniqueConstraint("character_id", "edition", "variant"),
        Index("ix_card_definitions_active_rarity", "is_active", "rarity"),
    )


class PlayerModel(Base):
    __tablename__ = "players"

    discord_user_id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=False,
    )
    coins: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    gems: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    event_tokens: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        server_default="0",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    owned_cards: Mapped[list[OwnedCardModel]] = relationship(back_populates="owner")
    series_priorities: Mapped[list[SeriesPriorityModel]] = relationship(back_populates="player")


class SeriesPriorityModel(Base):
    __tablename__ = "series_priorities"

    player_id: Mapped[int] = mapped_column(
        ForeignKey("players.discord_user_id", ondelete="CASCADE"),
        primary_key=True,
    )
    series_id: Mapped[UUID] = mapped_column(
        ForeignKey("series.id", ondelete="CASCADE"),
        primary_key=True,
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    player: Mapped[PlayerModel] = relationship(back_populates="series_priorities")
    series: Mapped[SeriesModel] = relationship()

    __table_args__ = (CheckConstraint("priority >= 0 AND priority <= 1000", name="valid_priority"),)


class DropModel(Base):
    __tablename__ = "drops"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    creator_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    guild_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    message_id: Mapped[int | None] = mapped_column(BigInteger, unique=True)
    status: Mapped[DropLifecycleStatus] = mapped_column(
        Enum(
            DropLifecycleStatus,
            values_callable=enum_values,
            native_enum=False,
            length=32,
            name="drop_lifecycle_status",
        ),
        nullable=False,
        default=DropLifecycleStatus.ACTIVE,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    slots: Mapped[list[DropSlotModel]] = relationship(
        back_populates="drop",
        cascade="all, delete-orphan",
        order_by="DropSlotModel.position",
    )

    __table_args__ = (
        CheckConstraint("expires_at > created_at", name="valid_expiration"),
        Index("ix_drops_channel_created", "channel_id", "created_at"),
    )


class DropSlotModel(Base):
    __tablename__ = "drop_slots"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    drop_id: Mapped[UUID] = mapped_column(
        ForeignKey("drops.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    definition_id: Mapped[UUID] = mapped_column(
        ForeignKey("card_definitions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    print_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[DropSlotStatus] = mapped_column(
        Enum(
            DropSlotStatus,
            values_callable=enum_values,
            native_enum=False,
            length=32,
            name="drop_slot_status",
        ),
        nullable=False,
        default=DropSlotStatus.AVAILABLE,
    )
    claimed_by: Mapped[int | None] = mapped_column(BigInteger)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    drop: Mapped[DropModel] = relationship(back_populates="slots")
    definition: Mapped[CardDefinitionModel] = relationship(back_populates="drop_slots")
    ownership: Mapped[OwnedCardModel | None] = relationship(
        back_populates="source_drop_slot",
        uselist=False,
    )

    __table_args__ = (
        UniqueConstraint("drop_id", "position"),
        UniqueConstraint("definition_id", "print_number"),
        CheckConstraint("position >= 0 AND position < 4", name="valid_position"),
        CheckConstraint("print_number > 0", name="positive_print_number"),
        Index("ix_drop_slots_drop_status", "drop_id", "status"),
    )


class OwnedCardModel(Base):
    __tablename__ = "owned_cards"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("players.discord_user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    definition_id: Mapped[UUID] = mapped_column(
        ForeignKey("card_definitions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    print_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source_drop_slot_id: Mapped[UUID] = mapped_column(
        ForeignKey("drop_slots.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    is_favorite: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    owner: Mapped[PlayerModel] = relationship(back_populates="owned_cards")
    definition: Mapped[CardDefinitionModel] = relationship(back_populates="owned_cards")
    source_drop_slot: Mapped[DropSlotModel] = relationship(back_populates="ownership")

    __table_args__ = (
        UniqueConstraint("definition_id", "print_number"),
        CheckConstraint("print_number > 0", name="positive_print_number"),
        Index("ix_owned_cards_owner_acquired", "owner_id", "acquired_at"),
    )


class TransactionModel(Base):
    __tablename__ = "transactions"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    player_id: Mapped[int] = mapped_column(
        ForeignKey("players.discord_user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    transaction_type: Mapped[str] = mapped_column(String(40), nullable=False)
    currency: Mapped[str] = mapped_column(String(20), nullable=False)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    balance_after: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reference_id: Mapped[str | None] = mapped_column(String(80))
    description: Mapped[str | None] = mapped_column(String(280))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        Index("ix_transactions_player_created", "player_id", "created_at"),
    )


class RewardClaimModel(Base):
    __tablename__ = "reward_claims"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    player_id: Mapped[int] = mapped_column(
        ForeignKey("players.discord_user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    reward_type: Mapped[str] = mapped_column(String(20), nullable=False)
    currency: Mapped[str] = mapped_column(String(20), nullable=False)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    streak: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    claim_date: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        UniqueConstraint("player_id", "reward_type", "claim_date", name="uq_one_claim_per_day"),
        Index("ix_reward_claims_player_type", "player_id", "reward_type"),
    )


class MarketplaceListingModel(Base):
    __tablename__ = "marketplace_listings"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    seller_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("players.discord_user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ownership_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("owned_cards.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    definition_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("card_definitions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    character_name: Mapped[str] = mapped_column(String(160), nullable=False)
    series_name: Mapped[str] = mapped_column(String(160), nullable=False)
    rarity: Mapped[str] = mapped_column(String(32), nullable=False)
    print_number: Mapped[int] = mapped_column(Integer, nullable=False)
    edition: Mapped[str] = mapped_column(String(80), nullable=False)
    variant: Mapped[str] = mapped_column(String(80), nullable=False)
    price: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=ListingStatus.ACTIVE.value,
        index=True,
    )
    image_path: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    sold_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    buyer_id: Mapped[int | None] = mapped_column(BigInteger, index=True)

    __table_args__ = (
        CheckConstraint("price > 0", name="positive_price"),
        Index("ix_marketplace_active_search", "status", "rarity", "created_at"),
        Index("ix_marketplace_seller_active", "seller_id", "status"),
    )


class TradeModel(Base):
    __tablename__ = "trades"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    player1_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    player2_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    state: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default="pending",
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    player1_card_slots: Mapped[list[TradeCardModel]] = relationship(
        back_populates="trade",
        cascade="all, delete-orphan",
        foreign_keys="TradeCardModel.trade_id",
        primaryjoin="TradeModel.id == TradeCardModel.trade_id",
        order_by="TradeCardModel.id",
    )


class TradeCardModel(Base):
    __tablename__ = "trade_cards"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    trade_id: Mapped[UUID] = mapped_column(
        ForeignKey("trades.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    ownership_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("owned_cards.id", ondelete="CASCADE"),
        nullable=False,
    )
    character_name: Mapped[str] = mapped_column(String(160), nullable=False)
    series_name: Mapped[str] = mapped_column(String(160), nullable=False)
    rarity: Mapped[str] = mapped_column(String(32), nullable=False)
    print_number: Mapped[int] = mapped_column(Integer, nullable=False)
    edition: Mapped[str] = mapped_column(String(80), nullable=False)
    variant: Mapped[str] = mapped_column(String(80), nullable=False)
    image_path: Mapped[str] = mapped_column(Text, nullable=False)

    trade: Mapped[TradeModel] = relationship(back_populates="player1_card_slots")
