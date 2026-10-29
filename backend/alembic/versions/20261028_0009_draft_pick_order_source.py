"""Distinguish live hero rosters from chronological draft picks.

Revision ID: 20261028_0009
Revises: 20261028_0008
Create Date: 2026-10-28

"""
from alembic import op
import sqlalchemy as sa


revision = "20261028_0009"
down_revision = "20261028_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "drafts",
        sa.Column(
            "pick_order_is_chronological",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
    )
    op.execute(
        sa.text(
            "UPDATE drafts SET pick_order_is_chronological = false "
            "FROM match_games "
            "WHERE drafts.match_game_id = match_games.id "
            "AND match_games.status = 'live'"
        )
    )


def downgrade() -> None:
    op.drop_column("drafts", "pick_order_is_chronological")
