from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Team(Base):
    __tablename__ = "teams"
    __table_args__ = (
        UniqueConstraint("provider", "external_team_id", name="uq_teams_provider_external_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    provider: Mapped[str] = mapped_column(String(100))
    external_team_id: Mapped[str] = mapped_column(String(200))
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    matches_as_team_one: Mapped[list["Match"]] = relationship(
        back_populates="team_one", foreign_keys="Match.team_one_id"
    )
    matches_as_team_two: Mapped[list["Match"]] = relationship(
        back_populates="team_two", foreign_keys="Match.team_two_id"
    )
    games_as_radiant: Mapped[list["MatchGame"]] = relationship(
        back_populates="radiant_team", foreign_keys="MatchGame.radiant_team_id"
    )
    games_as_dire: Mapped[list["MatchGame"]] = relationship(
        back_populates="dire_team", foreign_keys="MatchGame.dire_team_id"
    )


class Hero(Base):
    __tablename__ = "heroes"
    __table_args__ = (
        UniqueConstraint("provider", "external_hero_id", name="uq_heroes_provider_external_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    provider: Mapped[str] = mapped_column(String(100))
    external_hero_id: Mapped[str] = mapped_column(String(200))
    name: Mapped[str] = mapped_column(String(200))
    image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    batru_mapping: Mapped["BatruHeroMapping | None"] = relationship(
        back_populates="hero",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
    )


class BatruHeroMapping(Base):
    __tablename__ = "batru_hero_mappings"
    __table_args__ = (
        UniqueConstraint("hero_id", name="uq_batru_hero_mappings_hero"),
        UniqueConstraint("short_name", name="uq_batru_hero_mappings_short_name"),
        UniqueConstraint(
            "external_hero_id",
            name="uq_batru_hero_mappings_external_id",
        ),
        CheckConstraint("length(trim(short_name)) > 0", name="ck_batru_hero_mappings_short_name"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    hero_id: Mapped[UUID] = mapped_column(
        ForeignKey("heroes.id", ondelete="CASCADE"), nullable=False
    )
    external_hero_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    short_name: Mapped[str] = mapped_column(String(100))

    hero: Mapped[Hero] = relationship(back_populates="batru_mapping")


class Match(Base):
    __tablename__ = "matches"
    __table_args__ = (
        UniqueConstraint("provider", "external_match_id", name="uq_matches_provider_external_id"),
        CheckConstraint("team_one_id <> team_two_id", name="ck_matches_distinct_teams"),
        CheckConstraint(
            "format IS NULL OR format IN ('BO1', 'BO3', 'BO5')",
            name="ck_matches_format",
        ),
        Index("ix_matches_league_id", "league_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    provider: Mapped[str] = mapped_column(String(100))
    external_match_id: Mapped[str] = mapped_column(String(200))
    team_one_id: Mapped[UUID] = mapped_column(
        ForeignKey("teams.id", ondelete="RESTRICT"), nullable=False
    )
    team_two_id: Mapped[UUID] = mapped_column(
        ForeignKey("teams.id", ondelete="RESTRICT"), nullable=False
    )
    league_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    league_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    format: Mapped[str | None] = mapped_column(String(3), nullable=True)
    status: Mapped[str] = mapped_column(
        String(50), default="unknown", server_default=text("'unknown'")
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    team_one: Mapped[Team] = relationship(back_populates="matches_as_team_one", foreign_keys=[team_one_id])
    team_two: Mapped[Team] = relationship(back_populates="matches_as_team_two", foreign_keys=[team_two_id])
    games: Mapped[list["MatchGame"]] = relationship(
        back_populates="match", cascade="all, delete-orphan", passive_deletes=True
    )


class MatchGame(Base):
    __tablename__ = "match_games"
    __table_args__ = (
        UniqueConstraint("match_id", "game_number", name="uq_match_games_match_number"),
        UniqueConstraint("provider", "external_game_id", name="uq_match_games_provider_external_id"),
        CheckConstraint("game_number > 0", name="ck_match_games_positive_number"),
        CheckConstraint(
            "radiant_team_id IS NULL OR dire_team_id IS NULL OR radiant_team_id <> dire_team_id",
            name="ck_match_games_distinct_sides",
        ),
        CheckConstraint(
            "status IN ('unknown', 'scheduled', 'live', 'completed', 'cancelled')",
            name="ck_match_games_status",
        ),
        CheckConstraint(
            "duration_seconds IS NULL OR duration_seconds >= 0",
            name="ck_match_games_duration",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    match_id: Mapped[UUID] = mapped_column(
        ForeignKey("matches.id", ondelete="CASCADE"), nullable=False
    )
    game_number: Mapped[int] = mapped_column(Integer)
    provider: Mapped[str] = mapped_column(String(100))
    external_game_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    radiant_team_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("teams.id", ondelete="RESTRICT"), nullable=True
    )
    dire_team_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("teams.id", ondelete="RESTRICT"), nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(
        String(30), default="unknown", server_default=text("'unknown'")
    )
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    radiant_won: Mapped[bool | None] = mapped_column(nullable=True)
    radiant_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dire_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    details_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    details_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    match: Mapped[Match] = relationship(back_populates="games")
    radiant_team: Mapped[Team | None] = relationship(
        back_populates="games_as_radiant", foreign_keys=[radiant_team_id]
    )
    dire_team: Mapped[Team | None] = relationship(
        back_populates="games_as_dire", foreign_keys=[dire_team_id]
    )
    drafts: Mapped[list["Draft"]] = relationship(
        back_populates="match_game", cascade="all, delete-orphan", passive_deletes=True
    )


class Draft(Base):
    __tablename__ = "drafts"
    __table_args__ = (
        UniqueConstraint("match_game_id", "version", name="uq_drafts_game_version"),
        CheckConstraint("version > 0", name="ck_drafts_positive_version"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    match_game_id: Mapped[UUID] = mapped_column(
        ForeignKey("match_games.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    pick_order_is_chronological: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true"), nullable=False
    )

    match_game: Mapped[MatchGame] = relationship(back_populates="drafts")
    picks: Mapped[list["DraftPick"]] = relationship(
        back_populates="draft", cascade="all, delete-orphan", passive_deletes=True
    )
    predictions: Mapped[list["Prediction"]] = relationship(
        back_populates="draft", cascade="all, delete-orphan", passive_deletes=True
    )
    prediction_jobs: Mapped[list["PredictionJob"]] = relationship(
        back_populates="draft",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class DraftPick(Base):
    __tablename__ = "draft_picks"
    __table_args__ = (
        UniqueConstraint("draft_id", "pick_order", name="uq_draft_picks_order"),
        UniqueConstraint("draft_id", "hero_id", name="uq_draft_picks_hero"),
        CheckConstraint("pick_order > 0", name="ck_draft_picks_positive_order"),
        CheckConstraint("side IN ('radiant', 'dire')", name="ck_draft_picks_side"),
        CheckConstraint(
            "position IN ('pos_1', 'pos_2', 'pos_3', 'pos_4', 'pos_5', 'unknown')",
            name="ck_draft_picks_position",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    draft_id: Mapped[UUID] = mapped_column(
        ForeignKey("drafts.id", ondelete="CASCADE"), nullable=False
    )
    hero_id: Mapped[UUID] = mapped_column(
        ForeignKey("heroes.id", ondelete="RESTRICT"), nullable=False
    )
    side: Mapped[str] = mapped_column(String(10))
    position: Mapped[str] = mapped_column(
        String(10), default="unknown", server_default=text("'unknown'")
    )
    pick_order: Mapped[int] = mapped_column(Integer)

    draft: Mapped[Draft] = relationship(back_populates="picks")
    hero: Mapped[Hero] = relationship()


class Prediction(Base):
    __tablename__ = "predictions"
    __table_args__ = (
        CheckConstraint(
            "radiant_probability >= 0 AND radiant_probability <= 1",
            name="ck_predictions_radiant_probability",
        ),
        CheckConstraint(
            "dire_probability >= 0 AND dire_probability <= 1",
            name="ck_predictions_dire_probability",
        ),
        CheckConstraint("length(trim(model_name)) > 0", name="ck_predictions_model_name"),
        UniqueConstraint("draft_id", "model_name", name="uq_predictions_draft_model"),
        Index("ix_predictions_draft_calculated_at", "draft_id", "calculated_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    draft_id: Mapped[UUID] = mapped_column(
        ForeignKey("drafts.id", ondelete="CASCADE"), nullable=False
    )
    radiant_probability: Mapped[Decimal] = mapped_column(Numeric(8, 7))
    dire_probability: Mapped[Decimal] = mapped_column(Numeric(8, 7))
    model_name: Mapped[str] = mapped_column(
        String(100), default="default", server_default=text("'default'")
    )
    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    draft: Mapped[Draft] = relationship(back_populates="predictions")


class PredictionJob(Base):
    __tablename__ = "prediction_jobs"
    __table_args__ = (
        UniqueConstraint("draft_id", "model_name", name="uq_prediction_jobs_draft_model"),
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name="ck_prediction_jobs_status",
        ),
        CheckConstraint("attempt_count >= 0", name="ck_prediction_jobs_attempt_count"),
        CheckConstraint("length(trim(model_name)) > 0", name="ck_prediction_jobs_model_name"),
        CheckConstraint(
            "failure_code IS NULL OR failure_code IN "
            "('hero_mapping', 'batru_unavailable', 'invalid_draft', "
            "'invalid_response', 'worker_error')",
            name="ck_prediction_jobs_failure_code",
        ),
        Index("ix_prediction_jobs_status_created_at", "status", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    draft_id: Mapped[UUID] = mapped_column(
        ForeignKey("drafts.id", ondelete="CASCADE"), nullable=False
    )
    model_name: Mapped[str] = mapped_column(
        String(100), default="default", server_default=text("'default'")
    )
    status: Mapped[str] = mapped_column(
        String(20), default="queued", server_default=text("'queued'")
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(40), nullable=True)

    draft: Mapped[Draft] = relationship(back_populates="prediction_jobs")
