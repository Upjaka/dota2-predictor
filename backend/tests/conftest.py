from datetime import datetime, timezone
import os

os.environ["DATABASE_URL"] = (
    "postgresql+asyncpg://test:test@127.0.0.1:5432/dota_draft_predictor_test"
)

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.dependencies import get_db_session
from app.main import app
from app.models import (  # noqa: F401
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


@pytest_asyncio.fixture
async def api_client():
    class HealthSession:
        async def execute(self, _statement):
            return None

    async def override_db_session():
        yield HealthSession()

    app.dependency_overrides[get_db_session] = override_db_session
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_db_session, None)


@pytest_asyncio.fixture
async def sqlite_session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    sessions = async_sessionmaker(engine, expire_on_commit=False)
    yield sessions

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def sqlite_session(sqlite_session_factory):
    async with sqlite_session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def create_draft(sqlite_session):
    async def create(*, completed=True, pick_count=10, map_index=1):
        team_one = Team(
            provider="test",
            external_team_id=f"team-one-{map_index}",
            name="Radiant team",
        )
        team_two = Team(
            provider="test",
            external_team_id=f"team-two-{map_index}",
            name="Dire team",
        )
        match = Match(
            provider="test",
            external_match_id=f"series-{map_index}",
            team_one=team_one,
            team_two=team_two,
            status="unknown",
        )
        game = MatchGame(
            match=match,
            game_number=1,
            provider="test",
            external_game_id=f"map-{map_index}",
            status="completed",
        )
        draft = Draft(
            match_game=game,
            version=1,
            completed_at=datetime.now(timezone.utc) if completed else None,
        )
        for index in range(pick_count):
            side = "radiant" if index < 5 else "dire"
            hero = Hero(
                provider="opendota",
                external_hero_id=f"hero-{map_index}-{index}",
                name=f"Hero {index}",
            )
            hero.batru_mapping = BatruHeroMapping(
                external_hero_id=hero.external_hero_id,
                short_name=f"batru_hero_{map_index}_{index}"
            )
            draft.picks.append(
                DraftPick(
                    hero=hero,
                    side=side,
                    pick_order=index + 1,
                    position="unknown",
                )
            )
        sqlite_session.add(draft)
        await sqlite_session.commit()
        return draft.id

    return create
