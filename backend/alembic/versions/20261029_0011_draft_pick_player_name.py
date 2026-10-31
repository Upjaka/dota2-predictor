"""Repair the missing revision marker in the previously empty migration file.

Revision ID: 20261029_0011
Revises: 20261028_0010
"""

revision = "20261029_0011"
down_revision = "20261028_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
