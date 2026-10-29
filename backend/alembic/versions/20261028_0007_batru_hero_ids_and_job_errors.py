"""Persist verified Batru hero IDs and prediction failure categories.

Revision ID: 20261028_0007
Revises: 20261028_0006
Create Date: 2026-10-28

"""
from alembic import op
import sqlalchemy as sa


revision = "20261028_0007"
down_revision = "20261028_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "batru_hero_mappings",
        sa.Column("external_hero_id", sa.String(length=200), nullable=True),
    )
    op.create_unique_constraint(
        "uq_batru_hero_mappings_external_id",
        "batru_hero_mappings",
        ["external_hero_id"],
    )
    op.add_column(
        "prediction_jobs",
        sa.Column("failure_code", sa.String(length=40), nullable=True),
    )
    op.create_check_constraint(
        "ck_prediction_jobs_failure_code",
        "prediction_jobs",
        "failure_code IS NULL OR failure_code IN "
        "('hero_mapping', 'batru_unavailable', 'invalid_draft', "
        "'invalid_response', 'worker_error')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_prediction_jobs_failure_code",
        "prediction_jobs",
        type_="check",
    )
    op.drop_column("prediction_jobs", "failure_code")
    op.drop_constraint(
        "uq_batru_hero_mappings_external_id",
        "batru_hero_mappings",
        type_="unique",
    )
    op.drop_column("batru_hero_mappings", "external_hero_id")
