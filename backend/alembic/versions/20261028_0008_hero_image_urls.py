"""Store canonical hero portrait URLs.

Revision ID: 20261028_0008
Revises: 20261028_0007
Create Date: 2026-10-28

"""
from alembic import op
import sqlalchemy as sa


revision = "20261028_0008"
down_revision = "20261028_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("heroes", sa.Column("image_url", sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column("heroes", "image_url")
