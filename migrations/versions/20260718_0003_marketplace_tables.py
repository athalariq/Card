"""Add marketplace listings table.

Revision ID: 20260718_0003
Revises: 20260718_0002
Create Date: 2026-07-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260718_0003"
down_revision: str | Sequence[str] | None = "20260718_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "marketplace_listings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("seller_id", sa.BigInteger(), nullable=False),
        sa.Column("ownership_id", sa.Uuid(), nullable=False),
        sa.Column("definition_id", sa.Uuid(), nullable=False),
        sa.Column("character_name", sa.String(length=160), nullable=False),
        sa.Column("series_name", sa.String(length=160), nullable=False),
        sa.Column("rarity", sa.String(length=32), nullable=False),
        sa.Column("print_number", sa.Integer(), nullable=False),
        sa.Column("edition", sa.String(length=80), nullable=False),
        sa.Column("variant", sa.String(length=80), nullable=False),
        sa.Column("price", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("image_path", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("sold_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("buyer_id", sa.BigInteger(), nullable=True),
        sa.CheckConstraint("price > 0", name=op.f("ck_marketplace_listings_positive_price")),
        sa.ForeignKeyConstraint(
            ["seller_id"],
            ["players.discord_user_id"],
            name=op.f("fk_marketplace_listings_seller_id_players"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["ownership_id"],
            ["owned_cards.id"],
            name=op.f("fk_marketplace_listings_ownership_id_owned_cards"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["definition_id"],
            ["card_definitions.id"],
            name=op.f("fk_marketplace_listings_definition_id_card_definitions"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_marketplace_listings")),
        sa.UniqueConstraint(
            "ownership_id",
            name=op.f("uq_marketplace_listings_ownership_id"),
        ),
    )
    op.create_index(
        op.f("ix_marketplace_listings_seller_id"),
        "marketplace_listings",
        ["seller_id"],
    )
    op.create_index(
        op.f("ix_marketplace_listings_definition_id"),
        "marketplace_listings",
        ["definition_id"],
    )
    op.create_index(
        op.f("ix_marketplace_listings_status"),
        "marketplace_listings",
        ["status"],
    )
    op.create_index(
        op.f("ix_marketplace_listings_buyer_id"),
        "marketplace_listings",
        ["buyer_id"],
    )
    op.create_index(
        "ix_marketplace_active_search",
        "marketplace_listings",
        ["status", "rarity", "created_at"],
    )
    op.create_index(
        "ix_marketplace_seller_active",
        "marketplace_listings",
        ["seller_id", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_marketplace_seller_active",
        table_name="marketplace_listings",
    )
    op.drop_index(
        "ix_marketplace_active_search",
        table_name="marketplace_listings",
    )
    op.drop_index(
        op.f("ix_marketplace_listings_buyer_id"),
        table_name="marketplace_listings",
    )
    op.drop_index(
        op.f("ix_marketplace_listings_status"),
        table_name="marketplace_listings",
    )
    op.drop_index(
        op.f("ix_marketplace_listings_definition_id"),
        table_name="marketplace_listings",
    )
    op.drop_index(
        op.f("ix_marketplace_listings_seller_id"),
        table_name="marketplace_listings",
    )
    op.drop_table("marketplace_listings")
