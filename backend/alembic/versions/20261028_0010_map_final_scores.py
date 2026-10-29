"""Store final scores for individual maps.

Revision ID: 20261028_0010
Revises: 20261028_0009
Create Date: 2026-10-28

"""
from alembic import op
import sqlalchemy as sa


revision = "20261028_0010"
down_revision = "20261028_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "match_games",
        sa.Column("radiant_score", sa.Integer(), nullable=True),
    )
    op.add_column(
        "match_games",
        sa.Column("dire_score", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("match_games", "dire_score")
    op.drop_column("match_games", "radiant_score")
