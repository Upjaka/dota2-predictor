"""Persist map lifecycle and model-specific prediction jobs.

Revision ID: 20261027_0003
Revises: 20261026_0002
Create Date: 2026-10-27

"""
from alembic import op
import sqlalchemy as sa


revision = "20261027_0003"
down_revision = "20261026_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "match_games",
        sa.Column(
            "status",
            sa.String(length=30),
            server_default=sa.text("'unknown'"),
            nullable=False,
        ),
    )
    op.add_column("match_games", sa.Column("duration_seconds", sa.Integer(), nullable=True))
    op.add_column("match_games", sa.Column("radiant_won", sa.Boolean(), nullable=True))
    op.add_column(
        "match_games",
        sa.Column("details_checked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_match_games_status",
        "match_games",
        "status IN ('unknown', 'scheduled', 'live', 'completed', 'cancelled')",
    )
    op.create_check_constraint(
        "ck_match_games_duration",
        "match_games",
        "duration_seconds IS NULL OR duration_seconds >= 0",
    )

    op.add_column(
        "prediction_jobs",
        sa.Column(
            "model_name",
            sa.String(length=100),
            server_default=sa.text("'default'"),
            nullable=False,
        ),
    )
    op.drop_constraint("uq_prediction_jobs_draft", "prediction_jobs", type_="unique")
    op.create_check_constraint(
        "ck_prediction_jobs_model_name",
        "prediction_jobs",
        "length(trim(model_name)) > 0",
    )
    op.create_unique_constraint(
        "uq_prediction_jobs_draft_model",
        "prediction_jobs",
        ["draft_id", "model_name"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_prediction_jobs_draft_model", "prediction_jobs", type_="unique")
    op.drop_constraint("ck_prediction_jobs_model_name", "prediction_jobs", type_="check")
    op.create_unique_constraint(
        "uq_prediction_jobs_draft", "prediction_jobs", ["draft_id"]
    )
    op.drop_column("prediction_jobs", "model_name")

    op.drop_constraint("ck_match_games_duration", "match_games", type_="check")
    op.drop_constraint("ck_match_games_status", "match_games", type_="check")
    op.drop_column("match_games", "details_checked_at")
    op.drop_column("match_games", "radiant_won")
    op.drop_column("match_games", "duration_seconds")
    op.drop_column("match_games", "status")
