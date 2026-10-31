from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class TeamRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    provider: str
    external_team_id: str
    name: str


class MatchGameRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    match_id: UUID
    game_number: int
    provider: str
    external_game_id: str | None
    started_at: datetime | None
    status: str
    duration_seconds: int | None
    radiant_won: bool | None
    radiant_score: int | None
    dire_score: int | None
    winner_side: Literal["radiant", "dire", "unknown"] = "unknown"
    winner_team_id: UUID | None = None
    winner_team_name: str | None = None
    details_checked_at: datetime | None
    details_error: str | None
    radiant_team: TeamRead | None
    dire_team: TeamRead | None


class MatchSummary(BaseModel):
    id: UUID
    provider: str
    external_match_id: str
    status: str
    league_name: str | None
    format: str | None
    received_at: datetime
    start_time: datetime | None
    team_one: TeamRead
    team_two: TeamRead


class MatchDetail(MatchSummary):
    games: list[MatchGameRead]


class MatchListResponse(BaseModel):
    items: list[MatchSummary]
    total: int
    offset: int
    limit: int


class TournamentRead(BaseModel):
    id: str
    name: str


class DashboardDraftRead(BaseModel):
    version: int
    pick_count: int
    is_complete: bool
    pick_order_is_chronological: bool


class DashboardGameRead(BaseModel):
    id: UUID
    game_number: int
    started_at: datetime | None
    status: str
    radiant_score: int | None
    dire_score: int | None
    winner_side: Literal["radiant", "dire", "unknown"] = "unknown"
    winner_team_id: UUID | None = None
    winner_team_name: str | None = None
    details_error: str | None


class DashboardMatchRead(MatchSummary):
    current_game: DashboardGameRead | None
    draft: DashboardDraftRead | None
    has_prediction: bool
    prediction_job_status: Literal["queued", "running", "succeeded", "failed"] | None


class DashboardResponse(BaseModel):
    items: list[DashboardMatchRead]
    total: int
    offset: int
    limit: int
    tournaments: list[TournamentRead]


class DraftPickRead(BaseModel):
    id: UUID
    hero_id: UUID
    hero_name: str
    hero_image_url: str | None
    hero_provider: str
    external_hero_id: str
    side: Literal["radiant", "dire"]
    position: Literal["pos_1", "pos_2", "pos_3", "pos_4", "pos_5", "unknown"]
    pick_order: int | None


class DraftRead(BaseModel):
    id: UUID
    match_game_id: UUID
    version: int
    received_at: datetime
    completed_at: datetime | None
    is_complete: bool
    pick_order_is_chronological: bool
    picks: list[DraftPickRead]


class PredictionRead(BaseModel):
    id: UUID
    draft_id: UUID
    draft_version: int
    model_name: str
    radiant_probability: Decimal
    dire_probability: Decimal
    calculated_at: datetime


class PredictionListResponse(BaseModel):
    game_id: UUID
    items: list[PredictionRead]


class PredictionJobRead(BaseModel):
    draft_id: UUID
    draft_version: int
    model_name: str
    status: Literal["queued", "running", "succeeded", "failed"]
    failure_code: Literal[
        "hero_mapping",
        "batru_unavailable",
        "invalid_draft",
        "invalid_response",
        "worker_error",
    ] | None
    attempt_count: int
    created_at: datetime
    last_attempt_at: datetime | None
    completed_at: datetime | None
    last_error: str | None


class PredictionJobListResponse(BaseModel):
    game_id: UUID
    items: list[PredictionJobRead]
