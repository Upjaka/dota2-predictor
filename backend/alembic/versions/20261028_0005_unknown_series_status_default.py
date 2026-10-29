"""Default series status to unknown when the provider gives no state.

Revision ID: 20261028_0005
Revises: 20261027_0004
Create Date: 2026-10-28

"""
from alembic import op
import sqlalchemy as sa


revision = "20261028_0005"
down_revision = "20261027_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "matches",
        "status",
        existing_type=sa.String(length=50),
        existing_nullable=False,
        server_default=sa.text("'unknown'"),
    )


def downgrade() -> None:
    op.alter_column(
        "matches",
        "status",
        existing_type=sa.String(length=50),
        existing_nullable=False,
        server_default=sa.text("'scheduled'"),
    )
