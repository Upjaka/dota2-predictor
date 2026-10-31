"""Store role configurations with prediction results.

Revision ID: 20261031_0012
Revises: 20261029_0011
"""

from alembic import op
import sqlalchemy as sa


revision = "20261031_0012"
down_revision = "20261029_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "predictions",
        sa.Column("role_signature", sa.String(length=64), nullable=False, server_default="default"),
    )
    op.add_column("predictions", sa.Column("radiant_roles", sa.JSON(), nullable=True))
    op.add_column("predictions", sa.Column("dire_roles", sa.JSON(), nullable=True))
    op.drop_constraint("uq_predictions_draft_model", "predictions", type_="unique")
    op.create_unique_constraint(
        "uq_predictions_draft_model_roles",
        "predictions",
        ["draft_id", "model_name", "role_signature"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_predictions_draft_model_roles", "predictions", type_="unique")
    op.create_unique_constraint(
        "uq_predictions_draft_model", "predictions", ["draft_id", "model_name"]
    )
    op.drop_column("predictions", "dire_roles")
    op.drop_column("predictions", "radiant_roles")
    op.drop_column("predictions", "role_signature")
