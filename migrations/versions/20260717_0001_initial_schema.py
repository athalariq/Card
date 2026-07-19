"""Create the initial card, drop, and ownership schema.

Revision ID: 20260717_0001
Revises:
Create Date: 2026-07-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260717_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

card_rarity = sa.Enum(
    "common",
    "legendary",
    name="card_rarity",
    native_enum=False,
    length=32,
)
drop_lifecycle_status = sa.Enum(
    "active",
    "closed",
    name="drop_lifecycle_status",
    native_enum=False,
    length=32,
)
drop_slot_status = sa.Enum(
    "available",
    "claimed",
    "expired",
    name="drop_slot_status",
    native_enum=False,
    length=32,
)


def upgrade() -> None:
    op.create_table(
        "series",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("slug", sa.String(length=180), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_series")),
        sa.UniqueConstraint("name", name=op.f("uq_series_name")),
        sa.UniqueConstraint("slug", name=op.f("uq_series_slug")),
    )
    op.create_table(
        "players",
        sa.Column("discord_user_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("coins", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("gems", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("event_tokens", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("discord_user_id", name=op.f("pk_players")),
    )
    op.create_table(
        "characters",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("series_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("aliases", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["series_id"],
            ["series.id"],
            name=op.f("fk_characters_series_id_series"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_characters")),
        sa.UniqueConstraint("series_id", "name", name=op.f("uq_characters_series_id")),
    )
    op.create_index(op.f("ix_characters_series_id"), "characters", ["series_id"])

    op.create_table(
        "card_definitions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("character_id", sa.Uuid(), nullable=False),
        sa.Column("image_path", sa.Text(), nullable=False),
        sa.Column("frame_path", sa.Text(), nullable=True),
        sa.Column("rarity", card_rarity, nullable=False),
        sa.Column("edition", sa.String(length=80), nullable=False),
        sa.Column("variant", sa.String(length=80), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("release_date", sa.Date(), nullable=True),
        sa.Column("artist", sa.String(length=160), nullable=True),
        sa.Column("drop_weight", sa.Float(), nullable=False),
        sa.Column("next_print_number", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "drop_weight > 0",
            name=op.f("ck_card_definitions_positive_drop_weight"),
        ),
        sa.CheckConstraint(
            "next_print_number > 0",
            name=op.f("ck_card_definitions_positive_next_print_number"),
        ),
        sa.ForeignKeyConstraint(
            ["character_id"],
            ["characters.id"],
            name=op.f("fk_card_definitions_character_id_characters"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_card_definitions")),
        sa.UniqueConstraint(
            "character_id",
            "edition",
            "variant",
            name=op.f("uq_card_definitions_character_id"),
        ),
    )
    op.create_index(
        "ix_card_definitions_active_rarity",
        "card_definitions",
        ["is_active", "rarity"],
    )
    op.create_index(
        op.f("ix_card_definitions_character_id"),
        "card_definitions",
        ["character_id"],
    )
    op.create_index(op.f("ix_card_definitions_is_active"), "card_definitions", ["is_active"])
    op.create_index(op.f("ix_card_definitions_rarity"), "card_definitions", ["rarity"])

    op.create_table(
        "series_priorities",
        sa.Column("player_id", sa.BigInteger(), nullable=False),
        sa.Column("series_id", sa.Uuid(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "priority >= 0 AND priority <= 1000",
            name=op.f("ck_series_priorities_valid_priority"),
        ),
        sa.ForeignKeyConstraint(
            ["player_id"],
            ["players.discord_user_id"],
            name=op.f("fk_series_priorities_player_id_players"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["series_id"],
            ["series.id"],
            name=op.f("fk_series_priorities_series_id_series"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("player_id", "series_id", name=op.f("pk_series_priorities")),
    )

    op.create_table(
        "drops",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("creator_id", sa.BigInteger(), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=True),
        sa.Column("channel_id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=True),
        sa.Column("status", drop_lifecycle_status, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("expires_at > created_at", name=op.f("ck_drops_valid_expiration")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_drops")),
        sa.UniqueConstraint("message_id", name=op.f("uq_drops_message_id")),
    )
    op.create_index("ix_drops_channel_created", "drops", ["channel_id", "created_at"])
    op.create_index(op.f("ix_drops_creator_id"), "drops", ["creator_id"])
    op.create_index(op.f("ix_drops_guild_id"), "drops", ["guild_id"])

    op.create_table(
        "drop_slots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("drop_id", sa.Uuid(), nullable=False),
        sa.Column("definition_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("print_number", sa.Integer(), nullable=False),
        sa.Column("status", drop_slot_status, nullable=False),
        sa.Column("claimed_by", sa.BigInteger(), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "position >= 0 AND position < 4",
            name=op.f("ck_drop_slots_valid_position"),
        ),
        sa.CheckConstraint(
            "print_number > 0",
            name=op.f("ck_drop_slots_positive_print_number"),
        ),
        sa.ForeignKeyConstraint(
            ["definition_id"],
            ["card_definitions.id"],
            name=op.f("fk_drop_slots_definition_id_card_definitions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["drop_id"],
            ["drops.id"],
            name=op.f("fk_drop_slots_drop_id_drops"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_drop_slots")),
        sa.UniqueConstraint(
            "definition_id",
            "print_number",
            name=op.f("uq_drop_slots_definition_id"),
        ),
        sa.UniqueConstraint("drop_id", "position", name=op.f("uq_drop_slots_drop_id")),
    )
    op.create_index(op.f("ix_drop_slots_definition_id"), "drop_slots", ["definition_id"])
    op.create_index(op.f("ix_drop_slots_drop_id"), "drop_slots", ["drop_id"])
    op.create_index("ix_drop_slots_drop_status", "drop_slots", ["drop_id", "status"])

    op.create_table(
        "owned_cards",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("definition_id", sa.Uuid(), nullable=False),
        sa.Column("print_number", sa.Integer(), nullable=False),
        sa.Column("source_drop_slot_id", sa.Uuid(), nullable=False),
        sa.Column("is_favorite", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attributes", sa.JSON(), nullable=False),
        sa.CheckConstraint(
            "print_number > 0",
            name=op.f("ck_owned_cards_positive_print_number"),
        ),
        sa.ForeignKeyConstraint(
            ["definition_id"],
            ["card_definitions.id"],
            name=op.f("fk_owned_cards_definition_id_card_definitions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["players.discord_user_id"],
            name=op.f("fk_owned_cards_owner_id_players"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_drop_slot_id"],
            ["drop_slots.id"],
            name=op.f("fk_owned_cards_source_drop_slot_id_drop_slots"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_owned_cards")),
        sa.UniqueConstraint(
            "definition_id",
            "print_number",
            name=op.f("uq_owned_cards_definition_id"),
        ),
        sa.UniqueConstraint(
            "source_drop_slot_id",
            name=op.f("uq_owned_cards_source_drop_slot_id"),
        ),
    )
    op.create_index(op.f("ix_owned_cards_definition_id"), "owned_cards", ["definition_id"])
    op.create_index(op.f("ix_owned_cards_owner_id"), "owned_cards", ["owner_id"])
    op.create_index(
        "ix_owned_cards_owner_acquired",
        "owned_cards",
        ["owner_id", "acquired_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_owned_cards_owner_acquired", table_name="owned_cards")
    op.drop_index(op.f("ix_owned_cards_owner_id"), table_name="owned_cards")
    op.drop_index(op.f("ix_owned_cards_definition_id"), table_name="owned_cards")
    op.drop_table("owned_cards")
    op.drop_index("ix_drop_slots_drop_status", table_name="drop_slots")
    op.drop_index(op.f("ix_drop_slots_drop_id"), table_name="drop_slots")
    op.drop_index(op.f("ix_drop_slots_definition_id"), table_name="drop_slots")
    op.drop_table("drop_slots")
    op.drop_index(op.f("ix_drops_guild_id"), table_name="drops")
    op.drop_index(op.f("ix_drops_creator_id"), table_name="drops")
    op.drop_index("ix_drops_channel_created", table_name="drops")
    op.drop_table("drops")
    op.drop_table("series_priorities")
    op.drop_index(op.f("ix_card_definitions_rarity"), table_name="card_definitions")
    op.drop_index(op.f("ix_card_definitions_is_active"), table_name="card_definitions")
    op.drop_index(op.f("ix_card_definitions_character_id"), table_name="card_definitions")
    op.drop_index("ix_card_definitions_active_rarity", table_name="card_definitions")
    op.drop_table("card_definitions")
    op.drop_index(op.f("ix_characters_series_id"), table_name="characters")
    op.drop_table("characters")
    op.drop_table("players")
    op.drop_table("series")
