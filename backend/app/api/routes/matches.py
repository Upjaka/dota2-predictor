from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.dependencies import get_db_session
from app.models import Draft
from app.repositories.matches import MatchRepository
from app.schemas.matches import (
    DraftPickRead,
    DraftRead,
    MatchDetail,
    MatchGameRead,
    MatchListResponse,
    MatchSummary,
    PredictionJobListResponse,
    PredictionJobRead,
    PredictionListResponse,
    PredictionRead,
    TournamentRead,
)
from app.services.draft_completion import is_draft_complete

router = APIRouter()


@router.get("/matches", response_model=MatchListResponse)
async def list_matches(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    status: Annotated[
        Literal["unknown", "scheduled", "live", "completed", "cancelled"] | None,
        Query(),
    ] = None,
    tournament_id: Annotated[str | None, Query(min_length=1, max_length=200, pattern=r"^\S+$")] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    sort_order: Annotated[Literal["asc", "desc"], Query()] = "asc",
) -> MatchListResponse:
    rows, total = await MatchRepository(session).list_matches(
        status=status,
        tournament_id=tournament_id,
        offset=offset,
        limit=limit,
        sort_order=sort_order,
    )
    items = [
        MatchSummary(
            id=match.id,
            provider=match.provider,
            external_match_id=match.external_match_id,
            status=match.status,
            league_name=match.league_name,
            format=match.format,
            received_at=match.received_at,
            start_time=start_time,
            team_one=match.team_one,
            team_two=match.team_two,
        )
        for match, start_time in rows
    ]
    return MatchListResponse(items=items, total=total, offset=offset, limit=limit)


@router.get("/matches/tournaments", response_model=list[TournamentRead])
async def list_tournaments(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[TournamentRead]:
    tournaments = await MatchRepository(session).list_tournaments()
    return [TournamentRead(id=league_id, name=name) for league_id, name in tournaments]


@router.get("/matches/{match_id}", response_model=MatchDetail)
async def get_match(
    match_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> MatchDetail:
    match = await MatchRepository(session).get_match(match_id)
    if match is None:
        raise HTTPException(status_code=404, detail="Match not found.")

    start_time = min(
        (game.started_at for game in match.games if game.started_at is not None),
        default=None,
    )
    summary = MatchSummary(
        id=match.id,
        provider=match.provider,
        external_match_id=match.external_match_id,
        status=match.status,
        league_name=match.league_name,
        format=match.format,
        received_at=match.received_at,
        start_time=start_time,
        team_one=match.team_one,
        team_two=match.team_two,
    )
    return MatchDetail(
        **summary.model_dump(),
        games=[_serialize_game(game) for game in match.games],
    )


@router.get("/matches/{match_id}/games", response_model=list[MatchGameRead])
async def get_match_games(
    match_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[MatchGameRead]:
    games = await MatchRepository(session).get_games(match_id)
    if games is None:
        raise HTTPException(status_code=404, detail="Match not found.")
    return [_serialize_game(game) for game in games]


def _serialize_game(game) -> MatchGameRead:
    result = MatchGameRead.model_validate(game)
    if (
        game.status != "completed"
        or game.radiant_won is None
        or game.radiant_team is None
        or game.dire_team is None
        or game.radiant_team_id == game.dire_team_id
    ):
        return result
    if (
        game.radiant_score is not None
        and game.dire_score is not None
        and (
            (game.radiant_won and game.radiant_score < game.dire_score)
            or (not game.radiant_won and game.dire_score < game.radiant_score)
        )
    ):
        return result

    winner = game.radiant_team if game.radiant_won else game.dire_team
    side = "radiant" if game.radiant_won else "dire"
    return result.model_copy(
        update={
            "winner_side": side,
            "winner_team_id": winner.id,
            "winner_team_name": winner.name,
        }
    )


@router.get("/games/{game_id}/draft", response_model=DraftRead)
async def get_game_draft(
    game_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> DraftRead:
    game_exists, draft = await MatchRepository(session).get_latest_draft(game_id)
    if not game_exists:
        raise HTTPException(status_code=404, detail="Game not found.")
    if draft is None:
        raise HTTPException(status_code=404, detail="Draft not found for this game.")
    return _serialize_draft(draft)


@router.get("/games/{game_id}/predictions", response_model=PredictionListResponse)
async def get_game_predictions(
    game_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> PredictionListResponse:
    game_exists, rows = await MatchRepository(session).get_predictions(game_id)
    if not game_exists:
        raise HTTPException(status_code=404, detail="Game not found.")
    return PredictionListResponse(
        game_id=game_id,
        items=[
            PredictionRead(
                id=prediction.id,
                draft_id=prediction.draft_id,
                draft_version=version,
                model_name=prediction.model_name,
                radiant_probability=prediction.radiant_probability,
                dire_probability=prediction.dire_probability,
                calculated_at=prediction.calculated_at,
            )
            for prediction, version in rows
        ],
    )


@router.get(
    "/games/{game_id}/prediction-jobs",
    response_model=PredictionJobListResponse,
)
async def get_game_prediction_jobs(
    game_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> PredictionJobListResponse:
    game_exists, rows = await MatchRepository(session).get_prediction_jobs(game_id)
    if not game_exists:
        raise HTTPException(status_code=404, detail="Game not found.")
    return PredictionJobListResponse(
        game_id=game_id,
        items=[
            PredictionJobRead(
                draft_id=job.draft_id,
                draft_version=version,
                model_name=job.model_name,
                status=job.status,
                failure_code=job.failure_code,
                attempt_count=job.attempt_count,
                created_at=job.created_at,
                last_attempt_at=job.last_attempt_at,
                completed_at=job.completed_at,
                last_error=job.last_error,
            )
            for job, version in rows
        ],
    )


def _serialize_draft(draft: Draft) -> DraftRead:
    return DraftRead(
        id=draft.id,
        match_game_id=draft.match_game_id,
        version=draft.version,
        received_at=draft.received_at,
        completed_at=draft.completed_at,
        is_complete=is_draft_complete(draft.picks),
        pick_order_is_chronological=draft.pick_order_is_chronological,
        picks=[
            DraftPickRead(
                id=pick.id,
                hero_id=pick.hero_id,
                hero_name=pick.hero.name,
                hero_image_url=pick.hero.image_url,
                hero_provider=pick.hero.provider,
                external_hero_id=pick.hero.external_hero_id,
                side=pick.side,
                position=pick.position,
                pick_order=(
                    pick.pick_order
                    if draft.pick_order_is_chronological
                    else None
                ),
            )
            for pick in sorted(draft.picks, key=lambda item: item.pick_order)
        ],
    )
