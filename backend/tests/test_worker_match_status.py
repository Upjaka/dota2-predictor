from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.integrations.interfaces import (
    MatchSnapshot,
    ProviderDraft,
    ProviderDraftPick,
    ProviderHero,
    ProviderMap,
    ProviderTeam,
)
from app.integrations.interfaces import BatruHero
from app.integrations.opendota_errors import OpenDotaTemporaryError
from app.models import (
    BatruHeroMapping,
    Draft,
    DraftPick,
    Hero,
    Match,
    MatchGame,
    PredictionJob,
)
from app.workers.main import MatchMonitoringWorker


def snapshot(
    game_id: str, radiant_won: bool | None, series_type: int = 1
) -> MatchSnapshot:
    game = ProviderMap(
        external_game_id=game_id,
        game_number=None,
        started_at=datetime(2026, 10, 28, tzinfo=timezone.utc),
        duration_seconds=1800 if radiant_won is not None else None,
        radiant_team=ProviderTeam("team-1", "Radiant team"),
        dire_team=ProviderTeam("team-2", "Dire team"),
        status="completed" if radiant_won is not None else None,
        radiant_won=radiant_won,
        draft=None,
    )
    return MatchSnapshot(
        provider_match_id=game_id,
        provider_series_id="series-1",
        league_name="Tournament",
        league_id="league-1",
        series_type=series_type,
        radiant_team=game.radiant_team,
        dire_team=game.dire_team,
        map=game,
    )


def live_snapshot(status: str = "live") -> MatchSnapshot:
    game = ProviderMap(
        external_game_id="9065653541",
        game_number=None,
        started_at=datetime(2026, 10, 28, 13, 37, 23, tzinfo=timezone.utc),
        duration_seconds=None,
        radiant_team=ProviderTeam("10292107", "Astra Invicta"),
        dire_team=ProviderTeam("9823272", "Team Yandex"),
        status=status,
        radiant_won=None,
        draft=None,
    )
    return MatchSnapshot(
        provider_match_id="9065653541",
        provider_series_id="1160918",
        league_id="20395",
        series_type=1,
        radiant_team=game.radiant_team,
        dire_team=game.dire_team,
        map=game,
    )


@pytest.mark.asyncio
async def test_series_status_uses_score_and_duplicate_ingest_is_idempotent(
    sqlite_session_factory,
):
    worker = MatchMonitoringWorker(
        provider=SimpleNamespace(provider_name="opendota"),
        batru_client=object(),
        poll_interval_seconds=120,
        max_details_per_cycle=1,
        details_recheck_seconds=3600,
        job_stale_seconds=300,
        job_max_attempts=3,
        model_name="test",
        session_factory=sqlite_session_factory,
    )

    first_map = snapshot("game-1", True)
    await worker._upsert_snapshot(first_map)
    await worker._upsert_snapshot(first_map)

    async with sqlite_session_factory() as session:
        match = await session.scalar(select(Match))
        assert match is not None
        assert match.format == "BO3"
        assert match.status == "unknown"
        assert match.league_id == "league-1"
        assert match.league_name == "Tournament"
        assert await session.scalar(select(func.count()).select_from(MatchGame)) == 1

    await worker._upsert_snapshot(snapshot("game-2", False))
    async with sqlite_session_factory() as session:
        match = await session.scalar(select(Match))
        assert match is not None
        assert match.status == "unknown"

    await worker._upsert_snapshot(snapshot("game-3", True))
    await worker._upsert_snapshot(snapshot("game-1", None))

    async with sqlite_session_factory() as session:
        match = await session.scalar(select(Match))
        assert match is not None
        assert match.status == "completed"
        assert await session.scalar(select(func.count()).select_from(Match)) == 1
        assert await session.scalar(select(func.count()).select_from(MatchGame)) == 3


@pytest.mark.asyncio
async def test_live_match_is_persisted_idempotently_and_stale_status_cannot_downgrade(
    sqlite_session_factory,
):
    worker = MatchMonitoringWorker(
        provider=SimpleNamespace(provider_name="opendota"),
        batru_client=object(),
        poll_interval_seconds=30,
        max_details_per_cycle=1,
        details_recheck_seconds=3600,
        job_stale_seconds=300,
        job_max_attempts=3,
        model_name="test",
        session_factory=sqlite_session_factory,
    )

    live = live_snapshot()
    await worker._upsert_snapshot(live)
    await worker._upsert_snapshot(live)
    await worker._upsert_snapshot(
        replace(live, map=replace(live.map, status="scheduled"))
    )

    async with sqlite_session_factory() as session:
        match = await session.scalar(select(Match))
        game = await session.scalar(select(MatchGame))
        assert match is not None and game is not None
        assert match.status == "live"
        assert match.league_id == "20395"
        assert game.status == "live"
        assert await session.scalar(select(func.count()).select_from(Match)) == 1
        assert await session.scalar(select(func.count()).select_from(MatchGame)) == 1


@pytest.mark.asyncio
async def test_team_sides_are_persisted_per_map_when_teams_swap_sides(
    sqlite_session_factory,
):
    worker = MatchMonitoringWorker(
        provider=SimpleNamespace(provider_name="opendota"),
        batru_client=object(),
        poll_interval_seconds=30,
        max_details_per_cycle=1,
        details_recheck_seconds=3600,
        job_stale_seconds=300,
        job_max_attempts=3,
        model_name="test",
        session_factory=sqlite_session_factory,
    )
    first_map = snapshot("game-1", True)
    await worker._upsert_snapshot(first_map)

    second_map = snapshot("game-2", False)
    second_map = replace(
        second_map,
        radiant_team=second_map.dire_team,
        dire_team=second_map.radiant_team,
        map=replace(
            second_map.map,
            radiant_team=second_map.dire_team,
            dire_team=second_map.radiant_team,
        ),
    )
    await worker._upsert_snapshot(second_map)

    async with sqlite_session_factory() as session:
        games = list(
            (
                await session.scalars(
                    select(MatchGame)
                    .options(
                        selectinload(MatchGame.radiant_team),
                        selectinload(MatchGame.dire_team),
                    )
                    .order_by(MatchGame.game_number)
                )
            ).all()
        )

    assert [(game.radiant_team.name, game.dire_team.name) for game in games] == [
        ("Radiant team", "Dire team"),
        ("Dire team", "Radiant team"),
    ]


@pytest.mark.asyncio
async def test_live_status_requires_an_active_game_and_completed_map_cannot_regress_or_erase_draft(
    sqlite_session_factory,
):
    worker = MatchMonitoringWorker(
        provider=SimpleNamespace(provider_name="opendota"),
        batru_client=object(),
        poll_interval_seconds=30,
        max_details_per_cycle=1,
        details_recheck_seconds=3600,
        job_stale_seconds=300,
        job_max_attempts=3,
        model_name="test",
        session_factory=sqlite_session_factory,
    )
    async with sqlite_session_factory() as session:
        session.add_all(
            [
                Hero(
                    provider="opendota",
                    external_hero_id=str(hero_id),
                    name=f"Hero {hero_id}",
                )
                for hero_id in range(1, 11)
            ]
        )
        await session.commit()

    base = live_snapshot()
    complete_picks = tuple(
        ProviderDraftPick(
            external_hero_id=str(hero_id),
            side="radiant" if hero_id <= 5 else "dire",
            pick_order=hero_id,
        )
        for hero_id in range(1, 11)
    )
    completed_snapshot = replace(
        base,
        map=replace(
            base.map,
            status="completed",
            radiant_won=True,
            duration_seconds=1800,
            draft=ProviderDraft(complete_picks),
        ),
    )
    await worker._upsert_snapshot(completed_snapshot)

    # These stale live-feed snapshots must not reopen the map or delete its draft.
    await worker._upsert_snapshot(base)
    await worker._upsert_snapshot(
        replace(base, map=replace(base.map, draft=ProviderDraft(())))
    )

    async with sqlite_session_factory() as session:
        match = await session.scalar(select(Match))
        game = await session.scalar(select(MatchGame))
        drafts = list(
            (
                await session.scalars(
                    select(Draft).options(
                        selectinload(Draft.picks).joinedload(DraftPick.hero)
                    )
                )
            ).all()
        )
        assert match is not None and game is not None
        assert game.status == "completed"
        assert match.status == "unknown"
        assert len(drafts) == 1
        assert drafts[0].completed_at is not None
        assert len(drafts[0].picks) == 10
        assert await session.scalar(select(func.count()).select_from(PredictionJob)) == 1


@pytest.mark.asyncio
async def test_verified_map_result_is_idempotent_and_incomplete_updates_do_not_erase_it(
    sqlite_session_factory,
):
    worker = MatchMonitoringWorker(
        provider=SimpleNamespace(provider_name="opendota"),
        batru_client=object(),
        poll_interval_seconds=30,
        max_details_per_cycle=1,
        details_recheck_seconds=3600,
        job_stale_seconds=300,
        job_max_attempts=3,
        model_name="test",
        session_factory=sqlite_session_factory,
    )
    initial = snapshot("result-map", True)
    initial = replace(
        initial,
        map=replace(initial.map, radiant_score=30, dire_score=20),
    )
    await worker._upsert_snapshot(initial)
    await worker._upsert_snapshot(initial)

    missing_result = replace(
        initial,
        map=replace(
            initial.map,
            status=None,
            radiant_won=None,
            radiant_score=None,
            dire_score=None,
        ),
    )
    await worker._upsert_snapshot(missing_result)

    conflicting_result = replace(
        initial,
        map=replace(
            initial.map,
            radiant_won=False,
            radiant_score=10,
            dire_score=30,
        ),
    )
    await worker._upsert_snapshot(conflicting_result)

    async with sqlite_session_factory() as session:
        game = await session.scalar(select(MatchGame))
        assert game is not None
        assert game.status == "completed"
        assert game.radiant_won is True
        assert game.radiant_score == 30
        assert game.dire_score == 20
        assert await session.scalar(select(func.count()).select_from(MatchGame)) == 1


@pytest.mark.asyncio
async def test_series_stays_live_while_any_map_is_live_and_completes_only_at_winning_score(
    sqlite_session_factory,
):
    worker = MatchMonitoringWorker(
        provider=SimpleNamespace(provider_name="opendota"),
        batru_client=object(),
        poll_interval_seconds=30,
        max_details_per_cycle=1,
        details_recheck_seconds=3600,
        job_stale_seconds=300,
        job_max_attempts=3,
        model_name="test",
        session_factory=sqlite_session_factory,
    )
    await worker._upsert_snapshot(snapshot("game-1", True))
    live_game = snapshot("game-2", None)
    await worker._upsert_snapshot(
        replace(live_game, map=replace(live_game.map, status="live"))
    )

    async with sqlite_session_factory() as session:
        match = await session.scalar(select(Match))
        assert match is not None
        assert match.status == "live"

    await worker._upsert_snapshot(snapshot("game-2", True))
    async with sqlite_session_factory() as session:
        match = await session.scalar(select(Match))
        assert match is not None
        assert match.status == "completed"


@pytest.mark.asyncio
async def test_history_ingestion_continues_when_live_feed_is_unavailable(
    sqlite_session_factory, monkeypatch
):
    class Provider:
        provider_name = "opendota"

        async def get_live_matches(self):
            raise OpenDotaTemporaryError("live endpoint unavailable")

        async def get_current_matches(self):
            return [snapshot("history-game", None)]

    worker = MatchMonitoringWorker(
        provider=Provider(),
        batru_client=object(),
        poll_interval_seconds=30,
        max_details_per_cycle=1,
        details_recheck_seconds=3600,
        job_stale_seconds=300,
        job_max_attempts=3,
        model_name="test",
        session_factory=sqlite_session_factory,
    )

    async def no_op():
        return None

    monkeypatch.setattr(worker, "_sync_hero_directory", no_op)
    monkeypatch.setattr(worker, "_sync_batru_hero_directory", no_op)
    monkeypatch.setattr(worker, "_refresh_due_match_details", no_op)
    monkeypatch.setattr(worker, "_process_prediction_jobs", no_op)

    await worker.run_cycle()

    async with sqlite_session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(Match)) == 1
        game = await session.scalar(select(MatchGame))
        assert game is not None
        assert game.external_game_id == "history-game"


@pytest.mark.asyncio
async def test_live_games_are_not_sent_to_completed_match_details_endpoint(
    sqlite_session_factory,
):
    provider = SimpleNamespace(
        provider_name="opendota",
        get_match_details=AsyncMock(),
    )
    worker = MatchMonitoringWorker(
        provider=provider,
        batru_client=object(),
        poll_interval_seconds=30,
        max_details_per_cycle=1,
        details_recheck_seconds=3600,
        job_stale_seconds=300,
        job_max_attempts=3,
        model_name="test",
        session_factory=sqlite_session_factory,
    )
    await worker._upsert_snapshot(live_snapshot())

    await worker._refresh_due_match_details()

    provider.get_match_details.assert_not_awaited()
    async with sqlite_session_factory() as session:
        game = await session.scalar(select(MatchGame))
        assert game is not None
        assert game.details_error is None
        assert game.details_checked_at is None


@pytest.mark.asyncio
async def test_live_draft_is_incremental_idempotent_and_queues_when_complete(
    sqlite_session_factory,
):
    worker = MatchMonitoringWorker(
        provider=SimpleNamespace(provider_name="opendota"),
        batru_client=object(),
        poll_interval_seconds=30,
        max_details_per_cycle=1,
        details_recheck_seconds=3600,
        job_stale_seconds=300,
        job_max_attempts=3,
        model_name="test",
        session_factory=sqlite_session_factory,
    )
    async with sqlite_session_factory() as session:
        session.add_all(
            [
                Hero(
                    provider="opendota",
                    external_hero_id=str(hero_id),
                    name=f"Hero {hero_id}",
                )
                for hero_id in range(1, 11)
            ]
        )
        await session.commit()

    def picks(count):
        return tuple(
            ProviderDraftPick(
                external_hero_id=str(hero_id),
                side="radiant" if hero_id <= 5 else "dire",
                pick_order=hero_id,
            )
            for hero_id in range(1, count + 1)
        )

    base = live_snapshot()
    await worker._upsert_snapshot(
        replace(
            base,
            map=replace(
                base.map,
                draft=ProviderDraft(
                    picks(2),
                    pick_order_is_chronological=False,
                ),
            ),
        )
    )
    await worker._upsert_snapshot(
        replace(
            base,
            map=replace(
                base.map,
                draft=ProviderDraft(
                    picks(3),
                    pick_order_is_chronological=False,
                ),
            ),
        )
    )
    await worker._upsert_snapshot(base)

    async with sqlite_session_factory() as session:
        latest = await session.scalar(
            select(Draft)
            .options(selectinload(Draft.picks).joinedload(DraftPick.hero))
            .order_by(Draft.version.desc())
        )
        assert latest is not None
        assert latest.completed_at is None
        assert len(latest.picks) == 3
        assert latest.pick_order_is_chronological is False
        assert await session.scalar(select(func.count()).select_from(PredictionJob)) == 0

    completed = tuple(
        sorted(
            [
                ProviderDraftPick(
                    external_hero_id=str(hero_id),
                    side="radiant",
                    pick_order=(hero_id * 2) - 1,
                )
                for hero_id in range(1, 6)
            ]
            + [
                ProviderDraftPick(
                    external_hero_id=str(hero_id),
                    side="dire",
                    pick_order=(hero_id - 5) * 2,
                )
                for hero_id in range(6, 11)
            ],
            key=lambda pick: pick.pick_order,
        )
    )
    full_live_snapshot = replace(
        base,
        map=replace(
            base.map,
            status="live",
            draft=ProviderDraft(
                completed,
                pick_order_is_chronological=True,
            ),
        ),
    )
    await worker._upsert_snapshot(full_live_snapshot)
    await worker._upsert_snapshot(full_live_snapshot)

    async with sqlite_session_factory() as session:
        latest = await session.scalar(
            select(Draft)
            .options(selectinload(Draft.picks).joinedload(DraftPick.hero))
            .order_by(Draft.version.desc())
        )
        assert latest is not None
        assert latest.completed_at is not None
        assert len(latest.picks) == 10
        assert latest.version == 3
        assert latest.pick_order_is_chronological is True
        assert {
            pick.hero.external_hero_id: pick.pick_order for pick in latest.picks
        } == {
            **{str(hero_id): hero_id * 2 - 1 for hero_id in range(1, 6)},
            **{str(hero_id): (hero_id - 5) * 2 for hero_id in range(6, 11)},
        }
        assert {pick.side for pick in latest.picks} == {"radiant", "dire"}
        assert await session.scalar(select(func.count()).select_from(PredictionJob)) == 1
        job = await session.scalar(select(PredictionJob))
        assert job is not None
        assert job.status == "queued"

    completed_snapshot = replace(
        full_live_snapshot,
        map=replace(full_live_snapshot.map, status="completed", radiant_won=True),
    )
    await worker._upsert_snapshot(completed_snapshot)

    async with sqlite_session_factory() as session:
        jobs = await session.scalars(select(PredictionJob))
        assert len(list(jobs)) == 1
        game = await session.scalar(select(MatchGame))
        assert game is not None
        assert game.status == "completed"
        assert game.radiant_won is True


@pytest.mark.parametrize("map_status", ["unknown", "scheduled", "live", "completed"])
@pytest.mark.asyncio
async def test_prediction_job_is_created_only_after_full_canonical_draft(
    sqlite_session_factory, map_status
):
    worker = MatchMonitoringWorker(
        provider=SimpleNamespace(provider_name="opendota"),
        batru_client=object(),
        poll_interval_seconds=30,
        max_details_per_cycle=1,
        details_recheck_seconds=3600,
        job_stale_seconds=300,
        job_max_attempts=3,
        model_name="test",
        session_factory=sqlite_session_factory,
    )
    async with sqlite_session_factory() as session:
        session.add_all(
            [
                Hero(
                    provider="opendota",
                    external_hero_id=str(hero_id),
                    name=f"Hero {hero_id}",
                )
                for hero_id in range(1, 11)
            ]
        )
        await session.commit()

    def draft_for(hero_ids):
        return ProviderDraft(
            tuple(
                ProviderDraftPick(
                    external_hero_id=str(hero_id),
                    side="radiant" if hero_id <= 5 else "dire",
                    pick_order=index,
                )
                for index, hero_id in enumerate(hero_ids, start=1)
            ),
            pick_order_is_chronological=True,
        )

    base = live_snapshot(map_status)
    partial_snapshot = replace(
        base,
        map=replace(base.map, draft=draft_for(range(1, 10))),
    )
    await worker._upsert_snapshot(partial_snapshot)
    await worker._upsert_snapshot(partial_snapshot)

    async with sqlite_session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(PredictionJob)) == 0

    full_snapshot = replace(
        base,
        map=replace(base.map, draft=draft_for(range(1, 11))),
    )
    await worker._upsert_snapshot(full_snapshot)
    await worker._upsert_snapshot(full_snapshot)

    async with sqlite_session_factory() as session:
        jobs = list((await session.scalars(select(PredictionJob))).all())
        drafts = list(
            (
                await session.scalars(select(Draft).order_by(Draft.version))
            ).all()
        )
        assert len(jobs) == 1
        assert jobs[0].status == "queued"
        assert len(drafts) == 2
        assert drafts[-1].version == 2


@pytest.mark.asyncio
async def test_changed_complete_draft_gets_a_new_versioned_prediction_job(
    sqlite_session_factory,
):
    worker = MatchMonitoringWorker(
        provider=SimpleNamespace(provider_name="opendota"),
        batru_client=object(),
        poll_interval_seconds=30,
        max_details_per_cycle=1,
        details_recheck_seconds=3600,
        job_stale_seconds=300,
        job_max_attempts=3,
        model_name="test",
        session_factory=sqlite_session_factory,
    )
    async with sqlite_session_factory() as session:
        session.add_all(
            [
                Hero(
                    provider="opendota",
                    external_hero_id=str(hero_id),
                    name=f"Hero {hero_id}",
                )
                for hero_id in range(1, 12)
            ]
        )
        await session.commit()

    def complete_draft(hero_ids):
        return ProviderDraft(
            tuple(
                ProviderDraftPick(
                    external_hero_id=str(hero_id),
                    side="radiant" if index < 5 else "dire",
                    pick_order=index + 1,
                )
                for index, hero_id in enumerate(hero_ids)
            ),
            pick_order_is_chronological=True,
        )

    base = live_snapshot()
    initial = replace(
        base,
        map=replace(base.map, draft=complete_draft(range(1, 11))),
    )
    changed = replace(
        base,
        map=replace(base.map, draft=complete_draft((*range(1, 10), 11))),
    )
    await worker._upsert_snapshot(initial)
    await worker._upsert_snapshot(changed)
    await worker._upsert_snapshot(changed)

    async with sqlite_session_factory() as session:
        drafts = list(
            (
                await session.scalars(
                    select(Draft).order_by(Draft.version)
                )
            ).all()
        )
        jobs = list((await session.scalars(select(PredictionJob))).all())
        assert [draft.version for draft in drafts] == [1, 2]
        assert len(jobs) == 2


@pytest.mark.asyncio
async def test_map_details_queue_a_complete_draft_before_map_completion(
    sqlite_session_factory,
):
    worker = MatchMonitoringWorker(
        provider=SimpleNamespace(provider_name="opendota"),
        batru_client=object(),
        poll_interval_seconds=30,
        max_details_per_cycle=1,
        details_recheck_seconds=3600,
        job_stale_seconds=300,
        job_max_attempts=3,
        model_name="test",
        session_factory=sqlite_session_factory,
    )
    async with sqlite_session_factory() as session:
        session.add_all(
            [
                Hero(
                    provider="opendota",
                    external_hero_id=str(hero_id),
                    name=f"Hero {hero_id}",
                )
                for hero_id in range(1, 11)
            ]
        )
        await session.commit()

    base = live_snapshot("scheduled")
    await worker._upsert_snapshot(base)
    full_draft = ProviderDraft(
        tuple(
            ProviderDraftPick(
                str(hero_id),
                "radiant" if hero_id <= 5 else "dire",
                hero_id,
            )
            for hero_id in range(1, 11)
        ),
        pick_order_is_chronological=True,
    )
    await worker._persist_details(
        replace(base.map, draft=full_draft, status="scheduled")
    )

    async with sqlite_session_factory() as session:
        draft = await session.scalar(select(Draft))
        job = await session.scalar(select(PredictionJob))
        game = await session.scalar(select(MatchGame))
        assert game is not None and game.status == "scheduled"
        assert draft is not None and draft.completed_at is not None
        assert job is not None and job.status == "queued"


@pytest.mark.asyncio
async def test_live_drafts_stay_per_map_and_unknown_heroes_are_not_fabricated(
    sqlite_session_factory,
):
    worker = MatchMonitoringWorker(
        provider=SimpleNamespace(provider_name="opendota"),
        batru_client=object(),
        poll_interval_seconds=30,
        max_details_per_cycle=1,
        details_recheck_seconds=3600,
        job_stale_seconds=300,
        job_max_attempts=3,
        model_name="test",
        session_factory=sqlite_session_factory,
    )
    async with sqlite_session_factory() as session:
        session.add_all(
            [
                Hero(provider="opendota", external_hero_id="1", name="Hero 1"),
                Hero(provider="opendota", external_hero_id="2", name="Hero 2"),
            ]
        )
        await session.commit()

    base = live_snapshot()
    first_map_draft = ProviderDraft(
        picks=(
            ProviderDraftPick("1", "radiant", 1),
            ProviderDraftPick("999", "dire", 6),
        ),
        pick_order_is_chronological=False,
    )
    second_map_draft = ProviderDraft(
        picks=(ProviderDraftPick("2", "dire", 6),),
        pick_order_is_chronological=False,
    )
    await worker._upsert_snapshot(
        replace(base, map=replace(base.map, draft=first_map_draft))
    )
    second_map = replace(
        base,
        provider_match_id="9065653542",
        map=replace(
            base.map,
            external_game_id="9065653542",
            draft=second_map_draft,
        ),
    )
    await worker._upsert_snapshot(second_map)

    async with sqlite_session_factory() as session:
        drafts = list(
            (
                await session.scalars(
                    select(Draft).options(
                        selectinload(Draft.picks).joinedload(DraftPick.hero)
                    )
                )
            ).all()
        )
        assert len(drafts) == 2
        by_map = {}
        for draft in drafts:
            game = await session.get(MatchGame, draft.match_game_id)
            assert game is not None
            by_map[game.external_game_id] = [
                pick.hero.external_hero_id for pick in draft.picks
            ]
        assert by_map == {
            "9065653541": ["1"],
            "9065653542": ["2"],
        }
        assert all(not draft.pick_order_is_chronological for draft in drafts)
        assert await session.scalar(
            select(func.count()).select_from(Hero).where(Hero.external_hero_id == "999")
        ) == 0
        assert await session.scalar(select(func.count()).select_from(PredictionJob)) == 0


@pytest.mark.asyncio
async def test_complete_live_draft_queues_before_map_completion(
    sqlite_session_factory,
):
    worker = MatchMonitoringWorker(
        provider=SimpleNamespace(provider_name="opendota"),
        batru_client=object(),
        poll_interval_seconds=30,
        max_details_per_cycle=1,
        details_recheck_seconds=3600,
        job_stale_seconds=300,
        job_max_attempts=3,
        model_name="test",
        session_factory=sqlite_session_factory,
    )
    async with sqlite_session_factory() as session:
        session.add_all(
            [
                Hero(provider="opendota", external_hero_id=str(hero_id), name=f"Hero {hero_id}")
                for hero_id in range(1, 11)
            ]
        )
        await session.commit()

    base = live_snapshot()
    full_draft = ProviderDraft(
        tuple(
            ProviderDraftPick(
                str(hero_id),
                "radiant" if hero_id <= 5 else "dire",
                hero_id,
            )
            for hero_id in range(1, 11)
        ),
        pick_order_is_chronological=False,
    )
    await worker._upsert_snapshot(
        replace(base, map=replace(base.map, draft=full_draft))
    )

    async with sqlite_session_factory() as session:
        game = await session.scalar(select(MatchGame))
        draft = await session.scalar(
            select(Draft).options(selectinload(Draft.picks).joinedload(DraftPick.hero))
        )
        assert game is not None and game.status == "live"
        assert draft is not None and draft.completed_at is not None
        assert len(draft.picks) == 10
        job = await session.scalar(select(PredictionJob))
        assert job is not None and job.status == "queued"

    # A metadata-only poll retains the saved draft and does not enqueue a duplicate.
    completed_snapshot = replace(
        base,
        map=replace(
            base.map,
            status="completed",
            duration_seconds=1800,
            radiant_won=True,
            draft=None,
        ),
    )
    await worker._upsert_snapshot(completed_snapshot)
    await worker._upsert_snapshot(completed_snapshot)

    async with sqlite_session_factory() as session:
        game = await session.scalar(select(MatchGame))
        draft = await session.scalar(
            select(Draft).options(selectinload(Draft.picks).joinedload(DraftPick.hero))
        )
        assert game is not None and game.status == "completed"
        assert draft is not None and len(draft.picks) == 10
        jobs = list((await session.scalars(select(PredictionJob))).all())
        assert len(jobs) == 1
        assert jobs[0].status == "queued"


@pytest.mark.asyncio
async def test_corrected_side_assignment_recalculates_draft_completion(
    sqlite_session_factory,
):
    worker = MatchMonitoringWorker(
        provider=SimpleNamespace(provider_name="opendota"),
        batru_client=object(),
        poll_interval_seconds=30,
        max_details_per_cycle=1,
        details_recheck_seconds=3600,
        job_stale_seconds=300,
        job_max_attempts=3,
        model_name="test",
        session_factory=sqlite_session_factory,
    )
    async with sqlite_session_factory() as session:
        session.add_all(
            [
                Hero(provider="opendota", external_hero_id=str(hero_id), name=f"Hero {hero_id}")
                for hero_id in range(1, 11)
            ]
        )
        await session.commit()

    base = live_snapshot("completed")

    def draft_with_first_hero_on(side):
        return ProviderDraft(
            tuple(
                ProviderDraftPick(
                    str(hero_id),
                    side if hero_id == 1 else (
                        "radiant" if hero_id <= 5 else "dire"
                    ),
                    hero_id,
                )
                for hero_id in range(1, 11)
            )
        )

    await worker._upsert_snapshot(
        replace(base, map=replace(base.map, draft=draft_with_first_hero_on("radiant")))
    )
    await worker._upsert_snapshot(
        replace(base, map=replace(base.map, draft=draft_with_first_hero_on("dire")))
    )

    async with sqlite_session_factory() as session:
        latest = await session.scalar(
            select(Draft)
            .options(selectinload(Draft.picks).joinedload(DraftPick.hero))
            .order_by(Draft.version.desc())
        )
        game = await session.scalar(select(MatchGame))
        assert latest is not None and latest.completed_at is None
        assert sum(pick.side == "radiant" for pick in latest.picks) == 4
        assert sum(pick.side == "dire" for pick in latest.picks) == 6
        assert game is not None and game.status == "completed"

    await worker._upsert_snapshot(
        replace(base, map=replace(base.map, draft=draft_with_first_hero_on("radiant")))
    )

    async with sqlite_session_factory() as session:
        latest = await session.scalar(
            select(Draft)
            .options(selectinload(Draft.picks).joinedload(DraftPick.hero))
            .order_by(Draft.version.desc())
        )
        assert latest is not None and latest.completed_at is not None
        assert sum(pick.side == "radiant" for pick in latest.picks) == 5
        assert sum(pick.side == "dire" for pick in latest.picks) == 5


@pytest.mark.asyncio
async def test_full_snapshot_with_unknown_hero_excludes_it_from_completion(
    sqlite_session_factory,
):
    worker = MatchMonitoringWorker(
        provider=SimpleNamespace(provider_name="opendota"),
        batru_client=object(),
        poll_interval_seconds=30,
        max_details_per_cycle=1,
        details_recheck_seconds=3600,
        job_stale_seconds=300,
        job_max_attempts=3,
        model_name="test",
        session_factory=sqlite_session_factory,
    )
    async with sqlite_session_factory() as session:
        session.add_all(
            [
                Hero(provider="opendota", external_hero_id=str(hero_id), name=f"Hero {hero_id}")
                for hero_id in range(1, 11)
            ]
        )
        await session.commit()

    base = live_snapshot()
    good_picks = tuple(
        ProviderDraftPick(
            str(hero_id),
            "radiant" if hero_id <= 5 else "dire",
            hero_id,
        )
        for hero_id in range(1, 11)
    )
    await worker._upsert_snapshot(
        replace(
            base,
            map=replace(
                base.map,
                draft=ProviderDraft(good_picks, pick_order_is_chronological=False),
            ),
        )
    )

    unknown_picks = good_picks[:-1] + (
        ProviderDraftPick("999", "dire", 10),
    )
    await worker._upsert_snapshot(
        replace(
            base,
            map=replace(
                base.map,
                draft=ProviderDraft(
                    unknown_picks,
                    pick_order_is_chronological=False,
                ),
            ),
        )
    )

    async with sqlite_session_factory() as session:
        latest = await session.scalar(
            select(Draft)
            .options(selectinload(Draft.picks).joinedload(DraftPick.hero))
            .order_by(Draft.version.desc())
        )
        assert latest is not None
        assert latest.completed_at is None
        assert len(latest.picks) == 9
        jobs = list((await session.scalars(select(PredictionJob))).all())
        assert len(jobs) == 1
        assert jobs[0].draft_id != latest.id


@pytest.mark.asyncio
async def test_hero_directory_sync_persists_verified_portrait_urls(sqlite_session_factory):
    class Provider:
        provider_name = "opendota"

        async def get_hero_directory(self):
            return [
                ProviderHero(
                    external_hero_id="1",
                    name="Anti-Mage",
                    image_url="https://cdn.example/antimage.png",
                )
            ]

    worker = MatchMonitoringWorker(
        provider=Provider(),
        batru_client=object(),
        poll_interval_seconds=30,
        max_details_per_cycle=1,
        details_recheck_seconds=3600,
        job_stale_seconds=300,
        job_max_attempts=3,
        model_name="test",
        session_factory=sqlite_session_factory,
    )
    await worker._sync_hero_directory()

    async with sqlite_session_factory() as session:
        hero = await session.scalar(select(Hero))
        assert hero is not None
        assert hero.image_url == "https://cdn.example/antimage.png"


@pytest.mark.asyncio
async def test_completed_map_does_not_complete_bo3_series(sqlite_session_factory):
    worker = MatchMonitoringWorker(
        provider=SimpleNamespace(provider_name="opendota"),
        batru_client=object(),
        poll_interval_seconds=120,
        max_details_per_cycle=1,
        details_recheck_seconds=3600,
        job_stale_seconds=300,
        job_max_attempts=3,
        model_name="test",
        session_factory=sqlite_session_factory,
    )

    await worker._upsert_snapshot(snapshot("game-1", True))

    async with sqlite_session_factory() as session:
        match = await session.scalar(select(Match))
        game = await session.scalar(select(MatchGame))
        assert match is not None and game is not None
        assert game.status == "completed"
        assert match.status == "unknown"


@pytest.mark.asyncio
async def test_later_map_details_update_series_status(sqlite_session_factory):
    worker = MatchMonitoringWorker(
        provider=SimpleNamespace(provider_name="opendota"),
        batru_client=object(),
        poll_interval_seconds=120,
        max_details_per_cycle=1,
        details_recheck_seconds=3600,
        job_stale_seconds=300,
        job_max_attempts=3,
        model_name="test",
        session_factory=sqlite_session_factory,
    )
    await worker._upsert_snapshot(snapshot("game-1", None))
    await worker._upsert_snapshot(snapshot("game-2", None))

    first_details = snapshot("game-1", True).map
    second_details = snapshot("game-2", True).map
    assert first_details is not None and second_details is not None
    await worker._persist_details(first_details)

    async with sqlite_session_factory() as session:
        match = await session.scalar(select(Match))
        assert match is not None
        assert match.status == "unknown"

    await worker._persist_details(second_details)

    async with sqlite_session_factory() as session:
        match = await session.scalar(select(Match))
        assert match is not None
        assert match.status == "completed"


@pytest.mark.asyncio
async def test_bo5_series_waits_for_three_map_wins(sqlite_session_factory):
    worker = MatchMonitoringWorker(
        provider=SimpleNamespace(provider_name="opendota"),
        batru_client=object(),
        poll_interval_seconds=120,
        max_details_per_cycle=1,
        details_recheck_seconds=3600,
        job_stale_seconds=300,
        job_max_attempts=3,
        model_name="test",
        session_factory=sqlite_session_factory,
    )

    for game_number, radiant_won in enumerate(
        (True, False, True, False, True), start=1
    ):
        await worker._upsert_snapshot(
            snapshot(f"game-{game_number}", radiant_won, series_type=2)
        )
        async with sqlite_session_factory() as session:
            match = await session.scalar(select(Match))
            assert match is not None
            assert match.format == "BO5"
            assert match.status == (
                "completed" if game_number == 5 else "unknown"
            )


@pytest.mark.asyncio
async def test_batru_hero_directory_sync_is_idempotent(sqlite_session_factory):
    class BatruDirectory:
        async def get_hero_directory(self):
            return tuple(
                BatruHero(
                    external_hero_id=str(index),
                    canonical_name=f"npc_dota_hero_test_{index}",
                    display_name=f"Hero {index}",
                    short_name=f"test_hero_{index}",
                )
                for index in range(1, 128)
            )

    worker = MatchMonitoringWorker(
        provider=SimpleNamespace(provider_name="opendota"),
        batru_client=BatruDirectory(),
        poll_interval_seconds=120,
        max_details_per_cycle=1,
        details_recheck_seconds=3600,
        job_stale_seconds=300,
        job_max_attempts=3,
        model_name="test",
        session_factory=sqlite_session_factory,
    )

    await worker._sync_batru_hero_directory(force=True)
    await worker._sync_batru_hero_directory(force=True)

    async with sqlite_session_factory() as session:
        heroes = list((await session.scalars(select(Hero))).all())
        mappings = list((await session.scalars(select(BatruHeroMapping))).all())
        assert len(heroes) == len(mappings) == 127
        assert {
            mapping.external_hero_id: mapping.short_name
            for mapping in mappings
            if mapping.external_hero_id in {"1", "2"}
        } == {"1": "test_hero_1", "2": "test_hero_2"}


@pytest.mark.asyncio
async def test_batru_sync_preserves_conflicting_verified_identity(sqlite_session_factory):
    class BatruDirectory:
        async def get_hero_directory(self):
            return (
                BatruHero(
                    external_hero_id="1",
                    canonical_name="npc_dota_hero_antimage",
                    display_name="Anti-Mage",
                    short_name="antimage",
                ),
            )

    async with sqlite_session_factory() as session:
        async with session.begin():
            hero = Hero(
                provider="opendota",
                external_hero_id="1",
                name="Anti-Mage",
            )
            hero.batru_mapping = BatruHeroMapping(
                external_hero_id="999",
                short_name="existing_mapping",
            )
            session.add(hero)

    worker = MatchMonitoringWorker(
        provider=SimpleNamespace(provider_name="opendota"),
        batru_client=BatruDirectory(),
        poll_interval_seconds=120,
        max_details_per_cycle=1,
        details_recheck_seconds=3600,
        job_stale_seconds=300,
        job_max_attempts=3,
        model_name="test",
        session_factory=sqlite_session_factory,
    )

    await worker._sync_batru_hero_directory(force=True)

    async with sqlite_session_factory() as session:
        mapping = await session.scalar(select(BatruHeroMapping))
        assert mapping is not None
        assert mapping.external_hero_id == "999"
        assert mapping.short_name == "existing_mapping"


@pytest.mark.asyncio
async def test_batru_sync_requeues_legacy_mapping_failures_when_resolved(
    sqlite_session_factory, create_draft
):
    class BatruDirectory:
        async def get_hero_directory(self):
            return tuple(
                BatruHero(
                    external_hero_id=f"hero-{map_index}-{hero_index}",
                    canonical_name=f"npc_dota_hero_test_{map_index}_{hero_index}",
                    display_name=f"Hero {map_index}-{hero_index}",
                    short_name=f"test_hero_{map_index}_{hero_index}",
                )
                for map_index in (1, 2)
                for hero_index in range(10)
            )

    draft_ids = [await create_draft(map_index=index) for index in (1, 2)]
    async with sqlite_session_factory() as session:
        async with session.begin():
            for draft_id in draft_ids:
                draft = await session.scalar(
                    select(Draft)
                    .where(Draft.id == draft_id)
                    .options(
                        selectinload(Draft.picks).joinedload(DraftPick.hero)
                    )
                )
                assert draft is not None
                draft.picks[0].hero.batru_mapping = None
                session.add(
                    PredictionJob(
                        draft_id=draft_id,
                        model_name="test",
                        status="failed",
                        last_error=(
                            "One or more picked heroes have no verified Batru "
                            "shortName mapping."
                        ),
                    )
                )

    worker = MatchMonitoringWorker(
        provider=SimpleNamespace(provider_name="opendota"),
        batru_client=BatruDirectory(),
        poll_interval_seconds=120,
        max_details_per_cycle=1,
        details_recheck_seconds=3600,
        job_stale_seconds=300,
        job_max_attempts=3,
        model_name="test",
        session_factory=sqlite_session_factory,
    )

    await worker._sync_batru_hero_directory(force=True)

    async with sqlite_session_factory() as session:
        jobs = list((await session.scalars(select(PredictionJob))).all())
        assert len(jobs) == 2
        assert all(job.status == "queued" for job in jobs)
        assert all(job.failure_code is None for job in jobs)
        assert all(job.last_error is None for job in jobs)
