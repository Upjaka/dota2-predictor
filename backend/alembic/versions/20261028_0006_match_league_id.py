"""Persist stable OpenDota league IDs for match filtering.

Revision ID: 20261028_0006
Revises: 20261028_0005
Create Date: 2026-10-28

"""
from alembic import op
import sqlalchemy as sa


revision = "20261028_0006"
down_revision = "20261028_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("matches", sa.Column("league_id", sa.String(length=200), nullable=True))
    op.create_index("ix_matches_league_id", "matches", ["league_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_matches_league_id", table_name="matches")
    op.drop_column("matches", "league_id")
