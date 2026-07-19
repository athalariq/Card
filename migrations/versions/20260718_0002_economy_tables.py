"""Add economy tables (transactions, reward_claims).

Revision ID: 20260718_0002
Revises: 20260717_0001
Create Date: 2026-07-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260718_0002"
down_revision: str | Sequence[str] | None = "20260717_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "transactions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("player_id", sa.BigInteger(), nullable=False),
        sa.Column("transaction_type", sa.String(length=40), nullable=False),
        sa.Column("currency", sa.String(length=20), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("balance_after", sa.BigInteger(), nullable=False),
        sa.Column("reference_id", sa.String(length=80), nullable=True),
        sa.Column("description", sa.String(length=280), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["player_id"],
            ["players.discord_user_id"],
            name=op.f("fk_transactions_player_id_players"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_transactions")),
    )
    op.create_index(
        op.f("ix_transactions_player_id"),
        "transactions",
        ["player_id"],
    )
    op.create_index(
        "ix_transactions_player_created",
        "transactions",
        ["player_id", "created_at"],
    )

    op.create_table(
        "reward_claims",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("player_id", sa.BigInteger(), nullable=False),
        sa.Column("reward_type", sa.String(length=20), nullable=False),
        sa.Column("currency", sa.String(length=20), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("streak", sa.Integer(), nullable=False),
        sa.Column("claim_date", sa.Date(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["player_id"],
            ["players.discord_user_id"],
            name=op.f("fk_reward_claims_player_id_players"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reward_claims")),
        sa.UniqueConstraint(
            "player_id",
            "reward_type",
            "claim_date",
            name=op.f("uq_reward_claims_player_id"),
        ),
    )
    op.create_index(
        op.f("ix_reward_claims_player_id"),
        "reward_claims",
        ["player_id"],
    )
    op.create_index(
        "ix_reward_claims_player_type",
        "reward_claims",
        ["player_id", "reward_type"],
    )


def downgrade() -> None:
    op.drop_index("ix_reward_claims_player_type", table_name="reward_claims")
    op.drop_index(op.f("ix_reward_claims_player_id"), table_name="reward_claims")
    op.drop_table("reward_claims")
    op.drop_index("ix_transactions_player_created", table_name="transactions")
    op.drop_index(op.f("ix_transactions_player_id"), table_name="transactions")
    op.drop_table("transactions")
