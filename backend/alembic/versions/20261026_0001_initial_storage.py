"""Create initial match, draft, and prediction storage.

Revision ID: 20261026_0001
Revises:
Create Date: 2026-10-26

"""
from alembic import op
import sqlalchemy as sa


revision = "20261026_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "teams",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("external_team_id", sa.String(length=200), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "external_team_id", name="uq_teams_provider_external_id"),
    )
    op.create_table(
        "heroes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("external_hero_id", sa.String(length=200), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "external_hero_id", name="uq_heroes_provider_external_id"),
    )
    op.create_table(
        "matches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("external_match_id", sa.String(length=200), nullable=False),
        sa.Column("team_one_id", sa.Uuid(), nullable=False),
        sa.Column("team_two_id", sa.Uuid(), nullable=False),
        sa.Column("league_name", sa.String(length=200), nullable=True),
        sa.Column("format", sa.String(length=3), nullable=True),
        sa.Column("status", sa.String(length=50), server_default=sa.text("'scheduled'"), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("team_one_id <> team_two_id", name="ck_matches_distinct_teams"),
        sa.CheckConstraint("format IS NULL OR format IN ('BO1', 'BO3', 'BO5')", name="ck_matches_format"),
        sa.ForeignKeyConstraint(["team_one_id"], ["teams.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["team_two_id"], ["teams.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "external_match_id", name="uq_matches_provider_external_id"),
    )
    op.create_table(
        "match_games",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("match_id", sa.Uuid(), nullable=False),
        sa.Column("game_number", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("external_game_id", sa.String(length=200), nullable=True),
        sa.Column("radiant_team_id", sa.Uuid(), nullable=True),
        sa.Column("dire_team_id", sa.Uuid(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("game_number > 0", name="ck_match_games_positive_number"),
        sa.CheckConstraint(
            "radiant_team_id IS NULL OR dire_team_id IS NULL OR radiant_team_id <> dire_team_id",
            name="ck_match_games_distinct_sides",
        ),
        sa.ForeignKeyConstraint(["dire_team_id"], ["teams.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["match_id"], ["matches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["radiant_team_id"], ["teams.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("match_id", "game_number", name="uq_match_games_match_number"),
        sa.UniqueConstraint("provider", "external_game_id", name="uq_match_games_provider_external_id"),
    )
    op.create_table(
        "drafts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("match_game_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("version > 0", name="ck_drafts_positive_version"),
        sa.ForeignKeyConstraint(["match_game_id"], ["match_games.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("match_game_id", "version", name="uq_drafts_game_version"),
    )
    op.create_table(
        "draft_picks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("draft_id", sa.Uuid(), nullable=False),
        sa.Column("hero_id", sa.Uuid(), nullable=False),
        sa.Column("side", sa.String(length=10), nullable=False),
        sa.Column("position", sa.String(length=10), server_default=sa.text("'unknown'"), nullable=False),
        sa.Column("pick_order", sa.Integer(), nullable=False),
        sa.CheckConstraint("pick_order > 0", name="ck_draft_picks_positive_order"),
        sa.CheckConstraint("side IN ('radiant', 'dire')", name="ck_draft_picks_side"),
        sa.CheckConstraint(
            "position IN ('pos_1', 'pos_2', 'pos_3', 'pos_4', 'pos_5', 'unknown')",
            name="ck_draft_picks_position",
        ),
        sa.ForeignKeyConstraint(["draft_id"], ["drafts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["hero_id"], ["heroes.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("draft_id", "hero_id", name="uq_draft_picks_hero"),
        sa.UniqueConstraint("draft_id", "pick_order", name="uq_draft_picks_order"),
    )
    op.create_table(
        "prediction_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("draft_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default=sa.text("'queued'"), nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name="ck_prediction_jobs_status",
        ),
        sa.CheckConstraint("attempt_count >= 0", name="ck_prediction_jobs_attempt_count"),
        sa.ForeignKeyConstraint(["draft_id"], ["drafts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("draft_id", name="uq_prediction_jobs_draft"),
    )
    op.create_index(
        "ix_prediction_jobs_status_created_at",
        "prediction_jobs",
        ["status", "created_at"],
        unique=False,
    )
    op.create_table(
        "predictions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("draft_id", sa.Uuid(), nullable=False),
        sa.Column("radiant_probability", sa.Numeric(precision=8, scale=7), nullable=False),
        sa.Column("dire_probability", sa.Numeric(precision=8, scale=7), nullable=False),
        sa.Column("calculated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "radiant_probability >= 0 AND radiant_probability <= 1",
            name="ck_predictions_radiant_probability",
        ),
        sa.CheckConstraint(
            "dire_probability >= 0 AND dire_probability <= 1",
            name="ck_predictions_dire_probability",
        ),
        sa.ForeignKeyConstraint(["draft_id"], ["drafts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_predictions_draft_calculated_at",
        "predictions",
        ["draft_id", "calculated_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_predictions_draft_calculated_at", table_name="predictions")
    op.drop_table("predictions")
    op.drop_index("ix_prediction_jobs_status_created_at", table_name="prediction_jobs")
    op.drop_table("prediction_jobs")
    op.drop_table("draft_picks")
    op.drop_table("drafts")
    op.drop_table("match_games")
    op.drop_table("matches")
    op.drop_table("heroes")
    op.drop_table("teams")
