import asyncio
import logging
import signal
import time
from collections import Counter
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import httpx
from sqlalchemy import case, exists, func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.logging import configure_logging, cycle_id_var
from app.db.session import AsyncSessionLocal, engine
from app.integrations.batru_client import BatruClient
from app.integrations.batru_errors import (
    BatruError,
    BatruInvalidResponseError,
)
from app.integrations.interfaces import (
    MatchSnapshot,
    ProviderDraft,
    ProviderMap,
    ProviderTeam,
)
from app.integrations.opendota_errors import OpenDotaError
from app.integrations.opendota_provider import OpenDotaProvider
from app.models import (
    BatruHeroMapping,
    Draft,
    DraftPick,
    Hero,
    Match,
    MatchGame,
    Prediction,
    PredictionJob,
    Team,
)
from app.services.match_status import status_from_series_score
from app.services.draft_completion import is_draft_complete
from app.services.predictions import (
    HeroMappingError,
    InvalidDraftError,
    PredictionResponseError,
    PredictionService,
    PredictionServiceError,
)

logger = logging.getLogger(__name__)
UTC = timezone.utc


class WorkerDataError(ValueError):
    """Provider data cannot be safely persisted."""


class MatchMonitoringWorker:
    def __init__(
        self,
        *,
        provider: OpenDotaProvider,
        batru_client: BatruClient,
        poll_interval_seconds: float,
        max_details_per_cycle: int,
        details_recheck_seconds: float,
        job_stale_seconds: float,
        job_max_attempts: int,
        model_name: str,
        details_retry_seconds: float = 60.0,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self.provider = provider
        self.batru_client = batru_client
        self.poll_interval_seconds = poll_interval_seconds
        self.max_details_per_cycle = max_details_per_cycle
        self.details_recheck_seconds = details_recheck_seconds
        self.details_retry_seconds = details_retry_seconds
        self.job_stale_seconds = job_stale_seconds
        self.job_max_attempts = job_max_attempts
        self.model_name = model_name
        self._session_factory = session_factory or AsyncSessionLocal
        self._stop = asyncio.Event()
        self._hero_directory_loaded = False
        self._batru_hero_directory_synced_at: datetime | None = None

    def request_stop(self) -> None:
        self._stop.set()

    async def run(self) -> None:
        logger.info(
            "event=worker_started provider=%s poll_interval_seconds=%s "
            "max_details_per_cycle=%s model=%s",
            self.provider.provider_name,
            self.poll_interval_seconds,
            self.max_details_per_cycle,
            self.model_name,
        )
        while not self._stop.is_set():
            cycle_started = time.monotonic()
            try:
                await self.run_cycle()
            except Exception:
                # run_cycle has already logged the failure with its cycle_id.
                pass

            remaining = max(
                0.0, self.poll_interval_seconds - (time.monotonic() - cycle_started)
            )
            if remaining:
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=remaining)
                except asyncio.TimeoutError:
                    pass
        logger.info("event=worker_stopped")

    async def run_cycle(self) -> None:
        cycle_id = str(uuid4())
        token = cycle_id_var.set(cycle_id)
        started = time.perf_counter()
        logger.info("event=worker_cycle_started")
        try:
            await self._run_cycle()
        except Exception:
            logger.exception("event=worker_cycle_failed")
            raise
        finally:
            logger.info("event=worker_cycle_finished duration_ms=%.2f", (time.perf_counter() - started) * 1000)
            cycle_id_var.reset(token)

    async def _run_cycle(self) -> None:
        try:
            await self._sync_hero_directory()
        except (OpenDotaError, SQLAlchemyError):
            logger.exception("event=hero_directory_sync_failed")

        try:
            live_snapshots = await self.provider.get_live_matches()
        except OpenDotaError:
            logger.exception(
                "event=live_match_feed_unavailable provider=%s",
                self.provider.provider_name,
            )
        else:
            logger.info(
                "event=match_feed_received provider=%s feed=live count=%d",
                self.provider.provider_name,
                len(live_snapshots),
            )
            await self._ingest_snapshots(live_snapshots)

        try:
            await self._sync_batru_hero_directory()
        except (BatruError, SQLAlchemyError, WorkerDataError):
            logger.exception("event=batru_hero_directory_sync_failed")

        try:
            snapshots = await self.provider.get_current_matches()
        except OpenDotaError:
            logger.exception(
                "event=match_feed_unavailable provider=%s feed=history",
                self.provider.provider_name,
            )
        else:
            logger.info(
                "event=match_feed_received provider=%s feed=history count=%d",
                self.provider.provider_name,
                len(snapshots),
            )
            await self._ingest_snapshots(snapshots)

        await self._refresh_due_match_details()
        await self._process_prediction_jobs()

    async def _sync_hero_directory(self) -> None:
        if self._hero_directory_loaded:
            return
        heroes = await self.provider.get_hero_directory()
        if not heroes:
            logger.warning("event=hero_directory_empty provider=%s", self.provider.provider_name)
            return
        async with self._session_factory() as session:
            async with session.begin():
                for source_hero in heroes:
                    hero = await session.scalar(
                        select(Hero).where(
                            Hero.provider == self.provider.provider_name,
                            Hero.external_hero_id == source_hero.external_hero_id,
                        )
                    )
                    if hero is None:
                        session.add(
                            Hero(
                                provider=self.provider.provider_name,
                                external_hero_id=source_hero.external_hero_id,
                                name=source_hero.name,
                                image_url=source_hero.image_url,
                            )
                        )
                    else:
                        hero.name = source_hero.name
                        if source_hero.image_url:
                            hero.image_url = source_hero.image_url
        self._hero_directory_loaded = True
        logger.info("event=hero_directory_synced count=%d", len(heroes))

    async def _sync_batru_hero_directory(self, *, force: bool = False) -> None:
        if (
            not force
            and self._batru_hero_directory_synced_at is not None
            and datetime.now(UTC) - self._batru_hero_directory_synced_at
            < timedelta(days=1)
        ):
            return

        heroes = await self.batru_client.get_hero_directory()
        if not heroes:
            raise WorkerDataError("Batru hero directory is empty.")

        mapped = 0
        conflicts = 0
        requeued_jobs = 0
        async with self._session_factory() as session:
            async with session.begin():
                for source_hero in heroes:
                    hero = await session.scalar(
                        select(Hero).where(
                            Hero.provider == self.provider.provider_name,
                            Hero.external_hero_id == source_hero.external_hero_id,
                        )
                    )
                    if hero is None:
                        hero = Hero(
                            provider=self.provider.provider_name,
                            external_hero_id=source_hero.external_hero_id,
                            name=source_hero.display_name,
                        )
                        session.add(hero)
                        await session.flush()

                    mapping = await session.scalar(
                        select(BatruHeroMapping).where(
                            BatruHeroMapping.hero_id == hero.id
                        )
                    )
                    if (
                        mapping is not None
                        and mapping.external_hero_id is not None
                        and mapping.external_hero_id != source_hero.external_hero_id
                    ):
                        logger.error(
                            "event=batru_hero_mapping_conflict hero_id=%s "
                            "existing_external_id=%s directory_external_id=%s",
                            hero.id,
                            mapping.external_hero_id,
                            source_hero.external_hero_id,
                        )
                        conflicts += 1
                        continue

                    short_name_owner = await session.scalar(
                        select(BatruHeroMapping).where(
                            BatruHeroMapping.short_name == source_hero.short_name,
                            BatruHeroMapping.hero_id != hero.id,
                        )
                    )
                    external_id_owner = await session.scalar(
                        select(BatruHeroMapping).where(
                            BatruHeroMapping.external_hero_id
                            == source_hero.external_hero_id,
                            BatruHeroMapping.hero_id != hero.id,
                        )
                    )
                    if short_name_owner is not None or external_id_owner is not None:
                        logger.error(
                            "event=batru_mapping_identity_conflict hero_id=%s "
                            "external_hero_id=%s short_name=%s",
                            hero.id,
                            source_hero.external_hero_id,
                            source_hero.short_name,
                        )
                        conflicts += 1
                        continue

                    if mapping is None:
                        mapping = BatruHeroMapping(
                            hero_id=hero.id,
                            external_hero_id=source_hero.external_hero_id,
                            short_name=source_hero.short_name,
                        )
                        session.add(mapping)
                    else:
                        if mapping.short_name != source_hero.short_name:
                            logger.info(
                                "event=batru_hero_mapping_updated hero_id=%s "
                                "old_short_name=%s new_short_name=%s",
                                hero.id,
                                mapping.short_name,
                                source_hero.short_name,
                            )
                        mapping.external_hero_id = source_hero.external_hero_id
                        mapping.short_name = source_hero.short_name
                    mapped += 1
                requeued_jobs = await self._requeue_resolved_mapping_jobs(session)

        self._batru_hero_directory_synced_at = datetime.now(UTC)
        logger.info(
            "event=batru_hero_directory_synced mapped=%d conflicts=%d "
            "requeued_jobs=%d total=%d",
            mapped,
            conflicts,
            requeued_jobs,
            len(heroes),
        )

    async def _requeue_resolved_mapping_jobs(self, session: AsyncSession) -> int:
        jobs = list(
            (
                await session.scalars(
                    select(PredictionJob)
                    .where(
                        PredictionJob.status == "failed",
                        or_(
                            PredictionJob.failure_code == "hero_mapping",
                            PredictionJob.last_error.ilike(
                                "%no verified Batru shortName mapping%"
                            ),
                        ),
                    )
                    .options(
                        selectinload(PredictionJob.draft)
                        .selectinload(Draft.picks)
                        .joinedload(DraftPick.hero)
                        .joinedload(Hero.batru_mapping),
                        selectinload(PredictionJob.draft).selectinload(
                            Draft.match_game
                        ),
                    )
                    .order_by(PredictionJob.created_at.desc(), PredictionJob.id.desc())
                    .with_for_update()
                )
            ).all()
        )
        requeued = 0
        for job in jobs:
            picks = job.draft.picks
            if (
                not is_draft_complete(picks)
                or any(
                    pick.hero.batru_mapping is None
                    or pick.hero.batru_mapping.external_hero_id
                    != pick.hero.external_hero_id
                    for pick in picks
                )
            ):
                continue
            existing_prediction = await session.scalar(
                select(Prediction.id).where(
                    Prediction.draft_id == job.draft_id,
                    Prediction.model_name == job.model_name,
                )
            )
            if existing_prediction is not None:
                continue

            job.status = "queued"
            job.failure_code = None
            job.last_error = None
            job.completed_at = None
            requeued += 1
        return requeued

    async def _ingest_snapshots(self, snapshots: Sequence[MatchSnapshot]) -> None:
        unique_snapshots: dict[str, MatchSnapshot] = {}
        rejected = 0
        rejection_reasons: Counter[str] = Counter()
        rejected_samples: list[str] = []
        for snapshot in snapshots:
            if snapshot.provider_match_id in unique_snapshots:
                rejected += 1
                rejection_reasons["duplicate_match_in_feed"] += 1
                if len(rejected_samples) < 5:
                    rejected_samples.append(snapshot.provider_match_id)
                continue
            unique_snapshots[snapshot.provider_match_id] = snapshot

        status_counts = Counter(
            snapshot.map.status if snapshot.map and snapshot.map.status else "unknown"
            for snapshot in unique_snapshots.values()
        )
        inserted = 0
        updated = 0
        ordered = sorted(
            unique_snapshots.values(),
            key=lambda item: (
                item.map.started_at is None if item.map else True,
                item.map.started_at
                if item.map and item.map.started_at
                else datetime.max.replace(tzinfo=UTC),
                item.provider_match_id,
            ),
        )
        for snapshot in ordered:
            try:
                result = await self._upsert_snapshot(snapshot)
                if result is None:
                    rejected += 1
                    rejection_reasons["missing_map"] += 1
                elif result:
                    inserted += 1
                else:
                    updated += 1
            except WorkerDataError as exc:
                rejected += 1
                reason = str(exc)
                rejection_reasons[reason] += 1
                if len(rejected_samples) < 5:
                    rejected_samples.append(snapshot.provider_match_id)
            except Exception:
                rejected += 1
                rejection_reasons["unexpected_error"] += 1
                logger.exception(
                    "event=match_ingest_failed match_id=%s",
                    snapshot.provider_match_id,
                )
        logger.info(
            "event=match_feed_ingested provider=%s fetched=%d statuses=%s "
            "inserted=%d updated=%d rejected=%d rejection_reasons=%s "
            "rejected_sample_ids=%s",
            self.provider.provider_name,
            len(snapshots),
            ",".join(
                f"{status}:{count}" for status, count in sorted(status_counts.items())
            ),
            inserted,
            updated,
            rejected,
            ",".join(
                f"{reason}:{count}"
                for reason, count in sorted(rejection_reasons.items())
            )
            or "none",
            ",".join(rejected_samples) or "none",
        )

    async def _upsert_snapshot(self, snapshot: MatchSnapshot) -> bool | None:
        source_map = snapshot.map
        if source_map is None:
            logger.warning(
                "event=match_without_map_skipped match_id=%s", snapshot.provider_match_id
            )
            return None

        radiant_external_id = snapshot.radiant_team.external_team_id
        dire_external_id = snapshot.dire_team.external_team_id
        if not radiant_external_id or not dire_external_id:
            raise WorkerDataError("Provider match is missing a stable external team ID.")
        if radiant_external_id == dire_external_id:
            raise WorkerDataError("Provider identified the same team on both sides.")

        external_match_id = (
            f"series:{snapshot.provider_series_id}"
            if snapshot.provider_series_id
            else f"match:{snapshot.provider_match_id}"
        )
        inserted = False
        async with self._session_factory() as session:
            async with session.begin():
                radiant_team_id = await self._get_or_create_team_in_session(
                    session, snapshot.radiant_team
                )
                dire_team_id = await self._get_or_create_team_in_session(
                    session, snapshot.dire_team
                )
                if radiant_external_id < dire_external_id:
                    team_one_id, team_two_id = radiant_team_id, dire_team_id
                else:
                    team_one_id, team_two_id = dire_team_id, radiant_team_id
                match = await session.scalar(
                    select(Match).where(
                        Match.provider == self.provider.provider_name,
                        Match.external_match_id == external_match_id,
                    ).with_for_update()
                )
                if match is not None and {
                    match.team_one_id,
                    match.team_two_id,
                } != {team_one_id, team_two_id}:
                    raise WorkerDataError(
                        "Provider series ID was reused for a different team pair."
                    )
                if match is None:
                    match = Match(
                        provider=self.provider.provider_name,
                        external_match_id=external_match_id,
                        team_one_id=team_one_id,
                        team_two_id=team_two_id,
                        status="unknown",
                    )
                    session.add(match)
                    await session.flush()
                    inserted = True
                if snapshot.league_name:
                    match.league_name = snapshot.league_name
                elif snapshot.league_id and not match.league_name:
                    match.league_name = await session.scalar(
                        select(func.max(Match.league_name)).where(
                            Match.league_id == snapshot.league_id,
                            Match.league_name.is_not(None),
                        )
                    )
                if snapshot.league_id:
                    match.league_id = snapshot.league_id
                series_format = {1: "BO3", 2: "BO5"}.get(snapshot.series_type)
                if series_format:
                    match.format = series_format

                game = await session.scalar(
                    select(MatchGame).where(
                        MatchGame.provider == self.provider.provider_name,
                        MatchGame.external_game_id == source_map.external_game_id,
                    ).with_for_update()
                )
                if game is None:
                    last_game_number = await session.scalar(
                        select(func.max(MatchGame.game_number)).where(
                            MatchGame.match_id == match.id
                        )
                    )
                    game = MatchGame(
                        match_id=match.id,
                        game_number=(last_game_number or 0) + 1,
                        provider=self.provider.provider_name,
                        external_game_id=source_map.external_game_id,
                    )
                    session.add(game)
                    inserted = True
                elif game.match_id != match.id:
                    raise WorkerDataError(
                        "A provider game was previously associated with a different series."
                    )

                game.radiant_team_id = radiant_team_id
                game.dire_team_id = dire_team_id
                game.started_at = source_map.started_at or game.started_at
                if source_map.status:
                    game.status = _merge_provider_status(game.status, source_map.status)
                if game.status == "live":
                    game.details_checked_at = None
                    game.details_error = None
                if source_map.duration_seconds is not None:
                    game.duration_seconds = source_map.duration_seconds
                _apply_verified_map_result(game, source_map)
                if source_map.draft is not None:
                    await self._persist_draft(
                        session,
                        game,
                        source_map.draft,
                        source_map.status,
                    )
                await self._sync_draft_completion(session, game)
                await self._refresh_series_status(session, match)

        logger.info(
            "event=match_upserted match_id=%s map_id=%s series_id=%s map_status=%s",
            snapshot.provider_match_id,
            source_map.external_game_id,
            snapshot.provider_series_id or "unknown",
            source_map.status or "unknown",
        )
        return inserted

    async def _get_or_create_team_in_session(
        self, session: AsyncSession, source_team: ProviderTeam
    ) -> UUID:
        if not source_team.external_team_id:
            raise WorkerDataError("Provider match is missing a stable external team ID.")
        team = await session.scalar(
            select(Team).where(
                Team.provider == self.provider.provider_name,
                Team.external_team_id == source_team.external_team_id,
            )
        )
        if team is None:
            team = Team(
                provider=self.provider.provider_name,
                external_team_id=source_team.external_team_id,
                name=source_team.name or f"Unknown team {source_team.external_team_id}",
            )
            session.add(team)
            await session.flush()
        elif source_team.name:
            team.name = source_team.name
        return team.id

    async def _refresh_series_status(
        self, session: AsyncSession, match: Match
    ) -> None:
        if match.status == "completed":
            return

        result = await session.execute(
            select(
                MatchGame.radiant_team_id,
                MatchGame.dire_team_id,
                MatchGame.radiant_won,
                MatchGame.status,
            ).where(
                MatchGame.match_id == match.id,
            )
        )
        team_one_wins = 0
        team_two_wins = 0
        has_live_game = False
        for radiant_team_id, dire_team_id, radiant_won, game_status in result:
            if game_status == "live":
                has_live_game = True
                continue
            if (
                game_status != "completed"
                or radiant_won is None
                or radiant_team_id is None
                or dire_team_id is None
            ):
                continue
            winner_id = radiant_team_id if radiant_won else dire_team_id
            if winner_id == match.team_one_id:
                team_one_wins += 1
            elif winner_id == match.team_two_id:
                team_two_wins += 1

        status = status_from_series_score(
            match.status,
            match.format,
            team_one_wins,
            team_two_wins,
        )
        if status == "completed":
            match.status = status
        elif has_live_game:
            match.status = "live"
        elif match.status == "live":
            match.status = "unknown"
        else:
            match.status = status

    async def _refresh_due_match_details(self) -> None:
        cutoff = datetime.now(UTC) - timedelta(seconds=self.details_recheck_seconds)
        retry_cutoff = datetime.now(UTC) - timedelta(seconds=self.details_retry_seconds)
        radiant_five = (
            select(DraftPick.draft_id)
            .where(DraftPick.side == "radiant")
            .group_by(DraftPick.draft_id)
            .having(func.count(DraftPick.id) == 5)
        )
        dire_five = (
            select(DraftPick.draft_id)
            .where(DraftPick.side == "dire")
            .group_by(DraftPick.draft_id)
            .having(func.count(DraftPick.id) == 5)
        )
        has_complete_draft = exists(
            select(Draft.id).where(
                Draft.match_game_id == MatchGame.id,
                Draft.id.in_(radiant_five),
                Draft.id.in_(dire_five),
            )
        )
        async with self._session_factory() as session:
            due_ids = list(
                (
                    await session.scalars(
                        select(MatchGame.external_game_id)
                        .where(
                            MatchGame.provider == self.provider.provider_name,
                            MatchGame.external_game_id.is_not(None),
                            MatchGame.status != "live",
                            or_(
                                MatchGame.details_checked_at.is_(None),
                                (
                                    MatchGame.details_error.is_(None)
                                    & (MatchGame.details_checked_at <= cutoff)
                                ),
                                (
                                    MatchGame.details_error.is_not(None)
                                    & (MatchGame.details_checked_at <= retry_cutoff)
                                ),
                                (
                                    ~has_complete_draft
                                    & (MatchGame.details_checked_at <= retry_cutoff)
                                ),
                            ),
                        )
                        .order_by(
                            case(
                                (MatchGame.details_checked_at.is_(None), 0),
                                else_=1,
                            ),
                            MatchGame.details_checked_at,
                            MatchGame.game_number,
                        )
                        .limit(self.max_details_per_cycle)
                    )
                ).all()
            )

        for map_id in (item for item in due_ids if item is not None):
            try:
                details = await self.provider.get_match_details(map_id)
                if details.map.external_game_id != map_id:
                    raise WorkerDataError("Provider details returned a different map ID.")
                await self._persist_details(details.map)
            except Exception as exc:
                logger.exception("event=match_details_failed map_id=%s", map_id)
                try:
                    await self._record_details_attempt(map_id, exc)
                except SQLAlchemyError:
                    logger.exception(
                        "event=match_details_attempt_not_persisted map_id=%s",
                        map_id,
                    )

    async def _record_details_attempt(
        self, map_id: str, error: Exception
    ) -> None:
        async with self._session_factory() as session:
            async with session.begin():
                game = await session.scalar(
                    select(MatchGame).where(
                        MatchGame.provider == self.provider.provider_name,
                        MatchGame.external_game_id == map_id,
                    )
                )
                if game is not None:
                    game.details_checked_at = datetime.now(UTC)
                    game.details_error = f"{type(error).__name__}: {error}"[:4000]

    async def _persist_details(self, source_map: ProviderMap) -> None:
        async with self._session_factory() as session:
            async with session.begin():
                game = await session.scalar(
                    select(MatchGame)
                    .where(
                        MatchGame.provider == self.provider.provider_name,
                        MatchGame.external_game_id == source_map.external_game_id,
                    )
                    .with_for_update()
                )
                if game is None:
                    logger.warning(
                        "event=details_for_unknown_map map_id=%s",
                        source_map.external_game_id,
                    )
                    return

                game.started_at = source_map.started_at or game.started_at
                if source_map.status:
                    game.status = _merge_provider_status(game.status, source_map.status)
                if source_map.duration_seconds is not None:
                    game.duration_seconds = source_map.duration_seconds
                _apply_verified_map_result(game, source_map)
                game.details_checked_at = datetime.now(UTC)
                game.details_error = None
                match = await session.get(Match, game.match_id)
                if match is not None:
                    await self._refresh_series_status(session, match)
                if source_map.draft is not None:
                    await self._persist_draft(
                        session,
                        game,
                        source_map.draft,
                        source_map.status,
                    )
                await self._sync_draft_completion(session, game)

    async def _persist_draft(
        self,
        session: AsyncSession,
        game: MatchGame,
        source_draft: ProviderDraft,
        map_status: str | None,
    ) -> None:
        if not source_draft.picks:
            logger.info(
                "event=draft_empty_update_ignored map_id=%s map_status=%s",
                game.external_game_id,
                map_status or "unknown",
            )
            return

        incoming_picks = sorted(source_draft.picks, key=lambda pick: pick.pick_order)
        incoming_orders = [pick.pick_order for pick in incoming_picks]
        incoming_heroes = [pick.external_hero_id for pick in incoming_picks]
        if (
            len(set(incoming_orders)) != len(incoming_orders)
            or len(set(incoming_heroes)) != len(incoming_heroes)
        ):
            raise WorkerDataError(
                "Provider draft contains duplicate pick orders or heroes."
            )

        latest = await session.scalar(
            select(Draft)
            .where(Draft.match_game_id == game.id)
            .options(selectinload(Draft.picks).joinedload(DraftPick.hero))
            .order_by(Draft.version.desc())
            .limit(1)
        )

        stored_by_hero: dict[str, tuple[str, int, Hero]] = {}
        if latest is not None:
            for pick in latest.picks:
                stored_by_hero[pick.hero.external_hero_id] = (
                    pick.side,
                    pick.pick_order,
                    pick.hero,
                )

        resolved_incoming: list[tuple[ProviderDraftPick, Hero]] = []
        for source_pick in incoming_picks:
            if source_pick.side not in {"radiant", "dire"}:
                logger.warning(
                    "event=draft_pick_invalid_side map_id=%s hero_id=%s side=%s",
                    game.external_game_id,
                    source_pick.external_hero_id,
                    source_pick.side,
                )
                continue
            hero = await session.scalar(
                select(Hero).where(
                    Hero.provider == self.provider.provider_name,
                    Hero.external_hero_id == source_pick.external_hero_id,
                )
            )
            if hero is None:
                logger.warning(
                    "event=draft_pick_unknown_hero map_id=%s hero_id=%s",
                    game.external_game_id,
                    source_pick.external_hero_id,
                )
                continue
            resolved_incoming.append((source_pick, hero))

        # An apparent full snapshot is not authoritative if some heroes could
        # not be resolved yet; replacing in that case would erase known picks.
        replaces_full_snapshot = len(resolved_incoming) == 10
        if replaces_full_snapshot:
            stored_by_hero = {
                source_pick.external_hero_id: (
                    source_pick.side,
                    source_pick.pick_order,
                    hero,
                )
                for source_pick, hero in resolved_incoming
            }
        else:
            for source_pick, hero in resolved_incoming:
                existing = stored_by_hero.get(source_pick.external_hero_id)
                if existing is not None:
                    stored_by_hero[source_pick.external_hero_id] = (
                        source_pick.side,
                        existing[1],
                        hero,
                    )
                    continue
                order = source_pick.pick_order
                used_orders = {
                    pick_order
                    for _, pick_order, _ in stored_by_hero.values()
                }
                if order in used_orders:
                    order = max(used_orders, default=0) + 1
                stored_by_hero[source_pick.external_hero_id] = (
                    source_pick.side,
                    order,
                    hero,
                )

        if len(stored_by_hero) > 10:
            raise WorkerDataError("Provider draft contains more than ten unique heroes.")

        latest_snapshot = (
            {
                (pick.hero.external_hero_id, pick.side, pick.pick_order)
                for pick in latest.picks
            }
            if latest is not None
            else set()
        )
        current_snapshot = {
            (external_id, side, order)
            for external_id, (side, order, _) in stored_by_hero.items()
        }
        if (
            latest is not None
            and latest_snapshot == current_snapshot
            and latest.pick_order_is_chronological
            == source_draft.pick_order_is_chronological
        ):
            draft = latest
        else:
            version = latest.version + 1 if latest is not None else 1
            draft = Draft(
                match_game_id=game.id,
                version=version,
                pick_order_is_chronological=(
                    source_draft.pick_order_is_chronological
                ),
                picks=[],
            )
            session.add(draft)
            await session.flush()
            for external_id, (side, order, hero) in stored_by_hero.items():
                draft.picks.append(
                    DraftPick(
                        hero_id=hero.id,
                        hero=hero,
                        side=side,
                        pick_order=order,
                    )
                )
            await session.flush()

    async def _sync_draft_completion(
        self,
        session: AsyncSession,
        game: MatchGame,
    ) -> None:
        draft = await session.scalar(
            select(Draft)
            .where(Draft.match_game_id == game.id)
            .options(selectinload(Draft.picks).joinedload(DraftPick.hero))
            .order_by(Draft.version.desc())
            .limit(1)
        )
        if draft is None:
            return

        complete = is_draft_complete(draft.picks)
        if complete:
            draft.completed_at = draft.completed_at or datetime.now(UTC)
        else:
            draft.completed_at = None
        if complete:
            job = await session.scalar(
                select(PredictionJob).where(
                    PredictionJob.draft_id == draft.id,
                    PredictionJob.model_name == self.model_name,
                )
            )
            if job is None:
                session.add(
                    PredictionJob(
                        draft_id=draft.id,
                        model_name=self.model_name,
                        status="queued",
                    )
                )
                job_status = "queued"
            else:
                job_status = job.status
            logger.info(
                "event=draft_complete map_id=%s draft_version=%d "
                "prediction_job_status=%s",
                game.external_game_id,
                draft.version,
                job_status,
            )
        else:
            logger.info(
                "event=draft_incomplete map_id=%s picks=%d map_status=%s",
                game.external_game_id,
                len(draft.picks),
                game.status,
            )

    async def _process_prediction_jobs(self) -> None:
        await self._recover_stale_jobs()
        for _ in range(self.max_details_per_cycle):
            async with AsyncSessionLocal() as session:
                async with session.begin():
                    job = await session.scalar(
                        select(PredictionJob)
                        .where(PredictionJob.status == "queued")
                        .order_by(PredictionJob.created_at, PredictionJob.id)
                        .with_for_update(skip_locked=True)
                        .limit(1)
                    )
                    if job is None:
                        return
                    job.status = "running"
                    job.attempt_count += 1
                    job.last_attempt_at = datetime.now(UTC)
                    job.completed_at = None
                    job.last_error = None
                    job.failure_code = None
                    job_id = job.id
                    draft_id = job.draft_id
                    model_name = job.model_name
                    match_data = await session.execute(
                        select(Match.external_match_id, MatchGame.external_game_id)
                        .join(MatchGame, MatchGame.match_id == Match.id)
                        .join(Draft, Draft.match_game_id == MatchGame.id)
                        .where(Draft.id == draft_id)
                    )
                    match_id, map_id = match_data.one()

            try:
                async with AsyncSessionLocal() as session:
                    service = PredictionService(
                        session,
                        self.batru_client,
                        model_name=model_name,
                        max_retries=get_settings().batru_max_retries,
                        retry_backoff_seconds=get_settings().batru_retry_backoff_seconds,
                    )
                    prediction = await service.predict_draft(draft_id)
                await self._finish_job(job_id, "succeeded", None)
                logger.info(
                    "event=prediction_succeeded job_id=%s draft_id=%s "
                    "match_id=%s map_id=%s prediction_id=%s model=%s",
                    job_id,
                    draft_id,
                    match_id,
                    map_id,
                    prediction.id,
                    model_name,
                )
            except (BatruError, PredictionServiceError, SQLAlchemyError, ValueError) as exc:
                await self._finish_job(
                    job_id,
                    "failed",
                    str(exc),
                    failure_code=_prediction_failure_code(exc),
                )
                logger.exception(
                    "event=prediction_failed job_id=%s draft_id=%s "
                    "match_id=%s map_id=%s model=%s",
                    job_id,
                    draft_id,
                    match_id,
                    map_id,
                    model_name,
                )
            except Exception as exc:
                await self._finish_job(
                    job_id,
                    "failed",
                    str(exc),
                    failure_code="worker_error",
                )
                logger.exception(
                    "event=prediction_unexpected_failure job_id=%s draft_id=%s "
                    "match_id=%s map_id=%s model=%s",
                    job_id,
                    draft_id,
                    match_id,
                    map_id,
                    model_name,
                )

    async def _recover_stale_jobs(self) -> None:
        cutoff = datetime.now(UTC) - timedelta(seconds=self.job_stale_seconds)
        async with AsyncSessionLocal() as session:
            async with session.begin():
                jobs = list(
                    (
                        await session.scalars(
                            select(PredictionJob)
                            .where(
                                PredictionJob.status == "running",
                                or_(
                                    PredictionJob.last_attempt_at.is_(None),
                                    PredictionJob.last_attempt_at <= cutoff,
                                ),
                            )
                            .with_for_update(skip_locked=True)
                        )
                    ).all()
                )
                requeued = 0
                failed = 0
                for job in jobs:
                    if job.attempt_count >= self.job_max_attempts:
                        job.status = "failed"
                        job.completed_at = datetime.now(UTC)
                        job.last_error = (
                            "Maximum attempts reached after worker interruption."
                        )
                        job.failure_code = "worker_error"
                        failed += 1
                    else:
                        job.status = "queued"
                        job.last_error = (
                            "Recovered stale running job after worker interruption."
                        )
                        job.failure_code = None
                        requeued += 1
                if jobs:
                    logger.warning(
                        "event=stale_prediction_jobs_recovered count=%d requeued=%d failed=%d",
                        len(jobs),
                        requeued,
                        failed,
                    )

    async def _finish_job(
        self,
        job_id: UUID,
        status: str,
        error: str | None,
        *,
        failure_code: str | None = None,
    ) -> None:
        async with AsyncSessionLocal() as session:
            async with session.begin():
                job = await session.get(PredictionJob, job_id)
                if job is None:
                    raise WorkerDataError(f"Prediction job {job_id} disappeared.")
                job.status = status
                job.completed_at = datetime.now(UTC)
                job.last_error = error[:4000] if error else None
                job.failure_code = failure_code


def _prediction_failure_code(error: Exception) -> str:
    if isinstance(error, HeroMappingError):
        return "hero_mapping"
    if isinstance(error, InvalidDraftError):
        return "invalid_draft"
    if isinstance(error, (BatruInvalidResponseError, PredictionResponseError)):
        return "invalid_response"
    if isinstance(error, BatruError):
        return "batru_unavailable"
    return "worker_error"


def _apply_verified_map_result(game: MatchGame, source_map: ProviderMap) -> None:
    if source_map.status != "completed" or source_map.radiant_won is None:
        return

    if (
        source_map.radiant_score is not None
        and source_map.dire_score is not None
        and (
            (source_map.radiant_won and source_map.radiant_score < source_map.dire_score)
            or (
                not source_map.radiant_won
                and source_map.dire_score < source_map.radiant_score
            )
        )
    ):
        logger.warning(
            "event=map_result_conflict map_id=%s radiant_win=%s "
            "radiant_score=%d dire_score=%d",
            game.external_game_id,
            source_map.radiant_won,
            source_map.radiant_score,
            source_map.dire_score,
        )
        return

    if game.radiant_won is not None and game.radiant_won != source_map.radiant_won:
        logger.warning(
            "event=map_result_change_rejected map_id=%s stored_radiant_win=%s "
            "incoming_radiant_win=%s",
            game.external_game_id,
            game.radiant_won,
            source_map.radiant_won,
        )
        return

    game.radiant_won = source_map.radiant_won
    if source_map.radiant_score is not None and source_map.dire_score is not None:
        game.radiant_score = source_map.radiant_score
        game.dire_score = source_map.dire_score


def _merge_provider_status(current: str, incoming: str) -> str:
    if current == "completed" or current == "cancelled":
        return current
    if incoming == "completed" or incoming == "cancelled":
        return incoming
    status_rank = {"unknown": 0, "scheduled": 1, "live": 2}
    if status_rank.get(incoming, 0) >= status_rank.get(current, 0):
        return incoming
    return current


async def run() -> None:
    configure_logging()
    settings = get_settings()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for stop_signal in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(stop_signal, stop.set)
        except NotImplementedError:
            pass

    try:
        async with (
            httpx.AsyncClient(limits=httpx.Limits(max_connections=5)) as opendota_http,
            httpx.AsyncClient(limits=httpx.Limits(max_connections=5)) as batru_http,
        ):
            provider = OpenDotaProvider(
                base_url=settings.opendota_base_url,
                api_key=settings.opendota_api_key,
                timeout_seconds=settings.opendota_timeout_seconds,
                max_retries=settings.opendota_max_retries,
                retry_backoff_seconds=settings.opendota_retry_backoff_seconds,
                http_client=opendota_http,
            )
            batru_client = BatruClient(
                base_url=settings.batru_base_url,
                timeout_seconds=settings.batru_timeout_seconds,
                http_client=batru_http,
            )
            worker = MatchMonitoringWorker(
                provider=provider,
                batru_client=batru_client,
                poll_interval_seconds=settings.worker_poll_interval_seconds,
                max_details_per_cycle=settings.worker_max_details_per_cycle,
                details_recheck_seconds=settings.worker_details_recheck_seconds,
                details_retry_seconds=settings.worker_details_retry_seconds,
                job_stale_seconds=settings.worker_job_stale_seconds,
                job_max_attempts=settings.worker_job_max_attempts,
                model_name=settings.prediction_model_name,
            )
            stop_task = asyncio.create_task(stop.wait())
            run_task = asyncio.create_task(worker.run())
            await asyncio.wait(
                (stop_task, run_task), return_when=asyncio.FIRST_COMPLETED
            )
            worker.request_stop()
            await run_task
            stop_task.cancel()
            try:
                await stop_task
            except asyncio.CancelledError:
                pass
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run())
