"""Add trade tables.

Revision ID: 20260718_0004
Revises: 20260718_0003
Create Date: 2026-07-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260718_0004"
down_revision: str | Sequence[str] | None = "20260718_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "trades",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("player1_id", sa.BigInteger(), nullable=False),
        sa.Column("player2_id", sa.BigInteger(), nullable=False),
        sa.Column("state", sa.String(length=24), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_trades")),
    )
    op.create_index(
        op.f("ix_trades_player1_id"),
        "trades",
        ["player1_id"],
    )
    op.create_index(
        op.f("ix_trades_player2_id"),
        "trades",
        ["player2_id"],
    )
    op.create_index(
        op.f("ix_trades_state"),
        "trades",
        ["state"],
    )

    op.create_table(
        "trade_cards",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("trade_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("ownership_id", sa.Uuid(), nullable=False),
        sa.Column("character_name", sa.String(length=160), nullable=False),
        sa.Column("series_name", sa.String(length=160), nullable=False),
        sa.Column("rarity", sa.String(length=32), nullable=False),
        sa.Column("print_number", sa.Integer(), nullable=False),
        sa.Column("edition", sa.String(length=80), nullable=False),
        sa.Column("variant", sa.String(length=80), nullable=False),
        sa.Column("image_path", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["trade_id"],
            ["trades.id"],
            name=op.f("fk_trade_cards_trade_id_trades"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["ownership_id"],
            ["owned_cards.id"],
            name=op.f("fk_trade_cards_ownership_id_owned_cards"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_trade_cards")),
    )
    op.create_index(
        op.f("ix_trade_cards_trade_id"),
        "trade_cards",
        ["trade_id"],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_trade_cards_trade_id"), table_name="trade_cards")
    op.drop_table("trade_cards")
    op.drop_index(op.f("ix_trades_state"), table_name="trades")
    op.drop_index(op.f("ix_trades_player2_id"), table_name="trades")
    op.drop_index(op.f("ix_trades_player1_id"), table_name="trades")
    op.drop_table("trades")
