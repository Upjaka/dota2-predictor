from datetime import datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.models import Draft, DraftPick, Match, MatchGame, Prediction, PredictionJob


class MatchRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_matches(
        self,
        *,
        status: str | None,
        tournament_id: str | None = None,
        offset: int,
        limit: int,
        sort_order: Literal["asc", "desc"],
    ) -> tuple[list[tuple[Match, datetime | None]], int]:
        start_time = (
            select(func.min(MatchGame.started_at))
            .where(MatchGame.match_id == Match.id)
            .correlate(Match)
            .scalar_subquery()
        )
        filters = []
        if status is not None:
            filters.append(Match.status == status)
        if tournament_id is not None:
            filters.append(Match.league_id == tournament_id)

        total = await self.session.scalar(
            select(func.count()).select_from(Match).where(*filters)
        )
        ordering = start_time.asc().nulls_last()
        if sort_order == "desc":
            ordering = start_time.desc().nulls_last()

        result = await self.session.execute(
            select(Match, start_time.label("start_time"))
            .where(*filters)
            .options(joinedload(Match.team_one), joinedload(Match.team_two))
            .order_by(ordering, Match.id)
            .offset(offset)
            .limit(limit)
        )
        return list(result.all()), total or 0

    async def list_tournaments(self) -> list[tuple[str, str]]:
        result = await self.session.execute(
            select(Match.league_id, func.max(Match.league_name))
            .where(
                Match.league_id.is_not(None),
                Match.league_name.is_not(None),
                func.trim(Match.league_name) != "",
            )
            .group_by(Match.league_id)
            .order_by(func.lower(func.max(Match.league_name)), Match.league_id)
        )
        return [(league_id, league_name) for league_id, league_name in result.all()]

    async def get_match(self, match_id: UUID) -> Match | None:
        result = await self.session.execute(
            select(Match)
            .where(Match.id == match_id)
            .options(
                joinedload(Match.team_one),
                joinedload(Match.team_two),
                selectinload(Match.games).joinedload(MatchGame.radiant_team),
                selectinload(Match.games).joinedload(MatchGame.dire_team),
            )
        )
        return result.scalar_one_or_none()

    async def get_games(self, match_id: UUID) -> list[MatchGame] | None:
        match_exists = await self.session.scalar(
            select(Match.id).where(Match.id == match_id)
        )
        if match_exists is None:
            return None

        result = await self.session.execute(
            select(MatchGame)
            .where(MatchGame.match_id == match_id)
            .options(
                joinedload(MatchGame.radiant_team),
                joinedload(MatchGame.dire_team),
            )
            .order_by(MatchGame.game_number)
        )
        return list(result.scalars().all())

    async def get_latest_draft(self, game_id: UUID) -> tuple[bool, Draft | None]:
        game_exists = await self.session.scalar(
            select(MatchGame.id).where(MatchGame.id == game_id)
        )
        if game_exists is None:
            return False, None

        result = await self.session.execute(
            select(Draft)
            .where(Draft.match_game_id == game_id)
            .options(selectinload(Draft.picks).joinedload(DraftPick.hero))
            .order_by(Draft.version.desc())
            .limit(1)
        )
        return True, result.scalar_one_or_none()

    async def get_predictions(self, game_id: UUID) -> tuple[bool, list[tuple[Prediction, int]]]:
        game_exists = await self.session.scalar(
            select(MatchGame.id).where(MatchGame.id == game_id)
        )
        if game_exists is None:
            return False, []

        result = await self.session.execute(
            select(Prediction, Draft.version)
            .join(Draft, Prediction.draft_id == Draft.id)
            .where(Draft.match_game_id == game_id)
            .order_by(Prediction.calculated_at.desc(), Prediction.id)
        )
        return True, list(result.all())

    async def get_prediction_jobs(
        self, game_id: UUID
    ) -> tuple[bool, list[tuple[PredictionJob, int]]]:
        game_exists = await self.session.scalar(
            select(MatchGame.id).where(MatchGame.id == game_id)
        )
        if game_exists is None:
            return False, []

        result = await self.session.execute(
            select(PredictionJob, Draft.version)
            .join(Draft, PredictionJob.draft_id == Draft.id)
            .where(Draft.match_game_id == game_id)
            .order_by(Draft.version.desc(), PredictionJob.model_name)
        )
        return True, list(result.all())
