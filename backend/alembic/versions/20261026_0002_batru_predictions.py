"""Add Batru hero mappings and per-model prediction uniqueness.

Revision ID: 20261026_0002
Revises: 20261026_0001
Create Date: 2026-10-26

"""
from alembic import op
import sqlalchemy as sa


revision = "20261026_0002"
down_revision = "20261026_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "batru_hero_mappings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("hero_id", sa.Uuid(), nullable=False),
        sa.Column("short_name", sa.String(length=100), nullable=False),
        sa.CheckConstraint(
            "length(trim(short_name)) > 0",
            name="ck_batru_hero_mappings_short_name",
        ),
        sa.ForeignKeyConstraint(["hero_id"], ["heroes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("hero_id", name="uq_batru_hero_mappings_hero"),
        sa.UniqueConstraint("short_name", name="uq_batru_hero_mappings_short_name"),
    )
    op.add_column(
        "predictions",
        sa.Column(
            "model_name",
            sa.String(length=100),
            server_default=sa.text("'default'"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_predictions_model_name",
        "predictions",
        "length(trim(model_name)) > 0",
    )
    op.create_unique_constraint(
        "uq_predictions_draft_model",
        "predictions",
        ["draft_id", "model_name"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_predictions_draft_model", "predictions", type_="unique")
    op.drop_constraint("ck_predictions_model_name", "predictions", type_="check")
    op.drop_column("predictions", "model_name")
    op.drop_table("batru_hero_mappings")
