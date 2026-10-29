import asyncio
import os
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import func, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.mark.integration
def test_alembic_migrations_apply_to_dedicated_postgres_database(monkeypatch):
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Set TEST_DATABASE_URL to run PostgreSQL integration checks.")

    url = make_url(database_url)
    if not url.database or not url.database.endswith("_test"):
        pytest.fail("TEST_DATABASE_URL database name must end with '_test'.")
    if url.drivername != "postgresql+asyncpg":
        pytest.fail("TEST_DATABASE_URL must use postgresql+asyncpg.")
    if url.host not in {"localhost", "127.0.0.1", "::1"}:
        pytest.fail("TEST_DATABASE_URL must point to a local PostgreSQL test instance.")

    from alembic import command
    from alembic.config import Config
    from app.core.config import get_settings
    from app.models import Draft, Match, MatchGame, Prediction, Team
    from app.repositories.matches import MatchRepository

    backend_dir = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    config = Config(str(backend_dir / "alembic.ini"))
    command.upgrade(config, "head")

    async def verify_schema():
        engine = create_async_engine(database_url)
        try:
            async with engine.connect() as connection:
                tables = await connection.run_sync(
                    lambda sync_connection: set(
                        inspect(sync_connection).get_table_names()
                    )
                )
                columns = await connection.run_sync(
                    lambda sync_connection: {
                        column["name"]
                        for column in inspect(sync_connection).get_columns(
                            "match_games"
                        )
                    }
                )
                match_columns = await connection.run_sync(
                    lambda sync_connection: {
                        column["name"]
                        for column in inspect(sync_connection).get_columns("matches")
                    }
                )
                draft_columns = await connection.run_sync(
                    lambda sync_connection: {
                        column["name"]
                        for column in inspect(sync_connection).get_columns("drafts")
                    }
                )
                hero_columns = await connection.run_sync(
                    lambda sync_connection: {
                        column["name"]
                        for column in inspect(sync_connection).get_columns("heroes")
                    }
                )
                batru_mapping_columns = await connection.run_sync(
                    lambda sync_connection: {
                        column["name"]
                        for column in inspect(sync_connection).get_columns(
                            "batru_hero_mappings"
                        )
                    }
                )
                prediction_job_columns = await connection.run_sync(
                    lambda sync_connection: {
                        column["name"]
                        for column in inspect(sync_connection).get_columns(
                            "prediction_jobs"
                        )
                    }
                )
                match_status_default = await connection.run_sync(
                    lambda sync_connection: next(
                        column["default"]
                        for column in inspect(sync_connection).get_columns("matches")
                        if column["name"] == "status"
                    )
                )
                job_constraints = await connection.run_sync(
                    lambda sync_connection: {
                        constraint["name"]
                        for constraint in inspect(sync_connection).get_unique_constraints(
                            "prediction_jobs"
                        )
                    }
                )
                prediction_constraints = await connection.run_sync(
                    lambda sync_connection: {
                        constraint["name"]
                        for constraint in inspect(sync_connection).get_unique_constraints(
                            "predictions"
                        )
                    }
                )
            assert {"matches", "match_games", "drafts", "prediction_jobs", "predictions"} <= tables
            assert "details_error" in columns
            assert "pick_order_is_chronological" in draft_columns
            assert "league_id" in match_columns
            assert "image_url" in hero_columns
            assert "external_hero_id" in batru_mapping_columns
            assert "failure_code" in prediction_job_columns
            assert "unknown" in match_status_default
            assert "uq_prediction_jobs_draft_model" in job_constraints
            assert "uq_predictions_draft_model" in prediction_constraints

            sessions = async_sessionmaker(engine, expire_on_commit=False)
            async with sessions() as session:
                try:
                    team_one = Team(
                        provider="pytest",
                        external_team_id="repo-test-radiant",
                        name="Test Radiant",
                    )
                    team_two = Team(
                        provider="pytest",
                        external_team_id="repo-test-dire",
                        name="Test Dire",
                    )
                    match = Match(
                        provider="pytest",
                        external_match_id="repo-test-series",
                        team_one=team_one,
                        team_two=team_two,
                        status="integration-test",
                    )
                    match.games.append(
                        MatchGame(
                            game_number=1,
                            provider="pytest",
                            external_game_id="repo-test-map",
                            status="completed",
                        )
                    )
                    session.add(match)
                    await session.flush()

                    rows, total = await MatchRepository(session).list_matches(
                        status="integration-test",
                        offset=0,
                        limit=10,
                        sort_order="asc",
                    )
                    games = await MatchRepository(session).get_games(match.id)
                    assert total == 1
                    assert rows[0][0].external_match_id == "repo-test-series"
                    assert games is not None
                    assert [game.external_game_id for game in games] == ["repo-test-map"]

                    draft = Draft(
                        match_game=games[0],
                        version=1,
                        completed_at=datetime.now(timezone.utc),
                    )
                    session.add(draft)
                    await session.flush()
                    session.add(
                        Prediction(
                            draft=draft,
                            model_name="integration-test",
                            radiant_probability=Decimal("0.6000000"),
                            dire_probability=Decimal("0.4000000"),
                        )
                    )
                    await session.flush()

                    with pytest.raises(IntegrityError):
                        async with session.begin_nested():
                            session.add(
                                Prediction(
                                    draft=draft,
                                    model_name="integration-test",
                                    radiant_probability=Decimal("0.6000000"),
                                    dire_probability=Decimal("0.4000000"),
                                )
                            )
                            await session.flush()

                    prediction_count = await session.scalar(
                        select(func.count()).select_from(Prediction)
                    )
                    assert prediction_count == 1
                finally:
                    await session.rollback()
        finally:
            await engine.dispose()

    asyncio.run(verify_schema())
    get_settings.cache_clear()


@pytest.mark.integration
def test_concurrent_complete_draft_updates_enqueue_once(monkeypatch):
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Set TEST_DATABASE_URL to run PostgreSQL integration checks.")

    url = make_url(database_url)
    if (
        not url.database
        or not url.database.endswith("_test")
        or url.drivername != "postgresql+asyncpg"
        or url.host not in {"localhost", "127.0.0.1", "::1"}
    ):
        pytest.fail(
            "TEST_DATABASE_URL must point to a local postgresql+asyncpg "
            "database ending in '_test'."
        )

    from alembic import command
    from alembic.config import Config
    from app.core.config import get_settings
    from app.integrations.interfaces import (
        MatchSnapshot,
        ProviderDraft,
        ProviderDraftPick,
        ProviderMap,
        ProviderTeam,
    )
    from app.models import Draft, Hero, Match, MatchGame, PredictionJob
    from app.workers.main import MatchMonitoringWorker

    backend_dir = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    command.upgrade(Config(str(backend_dir / "alembic.ini")), "head")

    async def verify_concurrent_updates():
        engine = create_async_engine(database_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        suffix = uuid4().hex
        provider_name = f"worker-concurrency-{suffix}"
        radiant = ProviderTeam(f"radiant-{suffix}", "Test Radiant")
        dire = ProviderTeam(f"dire-{suffix}", "Test Dire")
        game_id = f"map-{suffix}"

        def snapshot(draft):
            provider_map = ProviderMap(
                external_game_id=game_id,
                game_number=1,
                started_at=datetime.now(timezone.utc),
                duration_seconds=None,
                radiant_team=radiant,
                dire_team=dire,
                status="live",
                radiant_won=None,
                draft=draft,
            )
            return MatchSnapshot(
                provider_match_id=game_id,
                provider_series_id=suffix,
                series_type=1,
                radiant_team=radiant,
                dire_team=dire,
                map=provider_map,
            )

        worker = MatchMonitoringWorker(
            provider=SimpleNamespace(provider_name=provider_name),
            batru_client=object(),
            poll_interval_seconds=30,
            max_details_per_cycle=1,
            details_recheck_seconds=3600,
            job_stale_seconds=300,
            job_max_attempts=3,
            model_name="concurrent-test",
            session_factory=sessions,
        )
        try:
            await worker._upsert_snapshot(snapshot(None))
            async with sessions() as session:
                session.add_all(
                    [
                        Hero(
                            provider=provider_name,
                            external_hero_id=f"{suffix}-{index}",
                            name=f"Test Hero {index}",
                        )
                        for index in range(10)
                    ]
                )
                await session.commit()

            full_draft = ProviderDraft(
                tuple(
                    ProviderDraftPick(
                        external_hero_id=f"{suffix}-{index}",
                        side="radiant" if index < 5 else "dire",
                        pick_order=index + 1,
                    )
                    for index in range(10)
                )
            )
            complete_snapshot = snapshot(full_draft)
            await asyncio.gather(
                worker._upsert_snapshot(complete_snapshot),
                worker._upsert_snapshot(complete_snapshot),
            )

            async with sessions() as session:
                game_id_in_db = await session.scalar(
                    select(MatchGame.id).where(
                        MatchGame.provider == provider_name,
                        MatchGame.external_game_id == game_id,
                    )
                )
                drafts = list(
                    (
                        await session.scalars(
                            select(Draft).where(
                                Draft.match_game_id == game_id_in_db
                            )
                        )
                    ).all()
                )
                jobs = list(
                    (
                        await session.scalars(
                            select(PredictionJob).where(
                                PredictionJob.draft_id.in_(
                                    select(Draft.id).where(
                                        Draft.match_game_id == game_id_in_db
                                    )
                                )
                            )
                        )
                    ).all()
                )
                assert len(drafts) == 1
                assert len(jobs) == 1
                assert jobs[0].draft_id == drafts[0].id
                assert jobs[0].status == "queued"
        finally:
            async with sessions() as session:
                await session.execute(
                    Match.__table__.delete().where(
                        Match.provider == provider_name,
                        Match.external_match_id == f"series:{suffix}",
                    )
                )
                await session.execute(
                    Hero.__table__.delete().where(Hero.provider == provider_name)
                )
                await session.commit()
            await engine.dispose()

    asyncio.run(verify_concurrent_updates())
    get_settings.cache_clear()


@pytest.mark.integration
def test_prediction_service_locks_only_draft_row_on_postgres(monkeypatch):
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Set TEST_DATABASE_URL to run PostgreSQL integration checks.")

    url = make_url(database_url)
    if (
        not url.database
        or not url.database.endswith("_test")
        or url.drivername != "postgresql+asyncpg"
        or url.host not in {"localhost", "127.0.0.1", "::1"}
    ):
        pytest.fail(
            "TEST_DATABASE_URL must point to a local postgresql+asyncpg "
            "database ending in '_test'."
        )

    from alembic import command
    from alembic.config import Config
    from app.core.config import get_settings
    from app.integrations.interfaces import DraftPrediction
    from app.models import (
        BatruHeroMapping,
        Draft,
        DraftPick,
        Hero,
        Match,
        MatchGame,
        Team,
    )
    from app.services.predictions import PredictionService

    backend_dir = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    command.upgrade(Config(str(backend_dir / "alembic.ini")), "head")

    class FakeBatruClient:
        def __init__(self):
            self.requests = []

        async def predict_draft(self, draft):
            self.requests.append(draft)
            return DraftPrediction(
                radiant_probability=Decimal("0.6"),
                dire_probability=Decimal("0.4"),
            )

    async def verify_prediction():
        engine = create_async_engine(database_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        suffix = uuid4().hex
        match_id = None
        team_ids = []
        hero_ids = []
        heroes = []
        try:
            async with sessions() as session:
                radiant = Team(
                    provider="prediction-lock-test",
                    external_team_id=f"radiant-{suffix}",
                    name="Test Radiant",
                )
                dire = Team(
                    provider="prediction-lock-test",
                    external_team_id=f"dire-{suffix}",
                    name="Test Dire",
                )
                match = Match(
                    provider="prediction-lock-test",
                    external_match_id=suffix,
                    team_one=radiant,
                    team_two=dire,
                    status="completed",
                )
                game = MatchGame(
                    match=match,
                    game_number=1,
                    provider="prediction-lock-test",
                    external_game_id=suffix,
                    status="completed",
                )
                draft = Draft(
                    match_game=game,
                    version=1,
                    completed_at=datetime.now(timezone.utc),
                    picks=[],
                )
                for index in range(10):
                    external_hero_id = f"{suffix}-{index}"
                    hero = Hero(
                        provider="prediction-lock-test",
                        external_hero_id=external_hero_id,
                        name=f"Test Hero {index}",
                    )
                    hero.batru_mapping = BatruHeroMapping(
                        external_hero_id=external_hero_id,
                        short_name=f"test_{suffix}_{index}",
                    )
                    draft.picks.append(
                        DraftPick(
                            hero=hero,
                            side="radiant" if index < 5 else "dire",
                            pick_order=index + 1,
                        )
                    )
                    heroes.append(hero)
                session.add(match)
                await session.flush()
                match_id = match.id
                team_ids = [radiant.id, dire.id]
                hero_ids = [hero.id for hero in heroes]
                draft_id = draft.id
                await session.commit()

            batru = FakeBatruClient()
            async with sessions() as session:
                result = await PredictionService(
                    session,
                    batru,
                    model_name="postgres-lock-test",
                    retry_backoff_seconds=0,
                ).predict_draft(draft_id)
                assert result.radiant_probability == Decimal("0.6000000")
            assert len(batru.requests) == 1
        finally:
            async with sessions() as session:
                if match_id is not None:
                    await session.execute(
                        Match.__table__.delete().where(Match.id == match_id)
                    )
                if hero_ids:
                    await session.execute(
                        Hero.__table__.delete().where(Hero.id.in_(hero_ids))
                    )
                if team_ids:
                    await session.execute(
                        Team.__table__.delete().where(Team.id.in_(team_ids))
                    )
                await session.commit()
            await engine.dispose()

    asyncio.run(verify_prediction())
    get_settings.cache_clear()
