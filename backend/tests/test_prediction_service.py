from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import joinedload, selectinload

from app.integrations.batru_errors import BatruTemporaryError
from app.integrations.interfaces import DraftPrediction
from app.models import Draft, DraftPick, Hero, Prediction
from app.services.predictions import (
    HeroMappingError,
    InvalidDraftError,
    PredictionResponseError,
    InvalidRoleAssignmentError,
    PredictionService,
)


def test_prediction_lock_only_targets_draft_table_for_postgres():
    statement = (
        select(Draft)
        .where(Draft.id == "draft-id")
        .options(
            selectinload(Draft.picks)
            .joinedload(DraftPick.hero)
            .joinedload(Hero.batru_mapping),
            joinedload(Draft.match_game),
        )
        .with_for_update(of=Draft)
    )

    sql = str(statement.compile(dialect=postgresql.dialect()))

    assert "LEFT OUTER JOIN match_games" in sql
    assert "FOR UPDATE OF drafts" in sql


class FakeBatruClient:
    def __init__(self, outcomes, session=None):
        self.outcomes = list(outcomes)
        self.requests = []
        self.session = session

    async def predict_draft(self, draft):
        if self.session is not None:
            assert not self.session.in_transaction()
        self.requests.append(draft)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def prediction(radiant="0.65", dire="0.35"):
    return DraftPrediction(
        radiant_probability=Decimal(radiant),
        dire_probability=Decimal(dire),
    )


@pytest.mark.asyncio
async def test_completed_draft_is_predicted_and_persisted_once(
    sqlite_session, create_draft
):
    draft_id = await create_draft(completed=False)
    batru = FakeBatruClient([prediction()], session=sqlite_session)
    service = PredictionService(sqlite_session, batru, retry_backoff_seconds=0)

    first = await service.predict_draft(draft_id)
    second = await service.predict_draft(draft_id)

    assert first.id == second.id
    assert first.radiant_probability == Decimal("0.6500000")
    assert first.dire_probability == Decimal("0.3500000")
    assert len(batru.requests) == 1
    assert list(batru.requests[0].radiant_heroes) == [
        f"batru_hero_1_{index}" for index in range(5)
    ]
    assert list(batru.requests[0].dire_heroes) == [
        f"batru_hero_1_{index}" for index in range(5, 10)
    ]
    assert await sqlite_session.scalar(select(func.count()).select_from(Prediction)) == 1


@pytest.mark.asyncio
async def test_role_aware_forecast_is_saved_per_distinct_role_configuration(
    sqlite_session, create_draft
):
    from app.models import Draft

    draft_id = await create_draft()
    draft = await sqlite_session.scalar(
        select(Draft).where(Draft.id == draft_id).options(selectinload(Draft.picks))
    )
    assignments = {
        pick.id: f"pos_{(index % 5) + 1}"
        for index, pick in enumerate(sorted(draft.picks, key=lambda item: item.pick_order))
    }
    await sqlite_session.commit()
    batru = FakeBatruClient([prediction(), prediction("0.55", "0.45")])
    service = PredictionService(sqlite_session, batru, retry_backoff_seconds=0)

    first = await service.predict_draft_with_roles(draft_id, assignments)
    repeated = await service.predict_draft_with_roles(draft_id, assignments)
    alternate = await service.predict_draft_with_roles(
        draft_id,
        {pick_id: f"pos_{(int(role[-1]) % 5) + 1}" for pick_id, role in assignments.items()},
    )

    assert first.id == repeated.id
    assert alternate.id != first.id
    assert first.model_name == "batru_plus"
    assert first.radiant_roles == [1, 2, 3, 4, 5]
    assert first.dire_roles == [1, 2, 3, 4, 5]
    assert list(batru.requests[0].radiant_roles) == [1, 2, 3, 4, 5]
    assert list(batru.requests[0].dire_roles) == [1, 2, 3, 4, 5]
    assert await sqlite_session.scalar(select(func.count()).select_from(Prediction)) == 2


@pytest.mark.asyncio
async def test_role_aware_forecast_rejects_missing_pick_role_without_calling_batru(
    sqlite_session, create_draft
):
    from app.models import Draft

    draft_id = await create_draft()
    draft = await sqlite_session.scalar(
        select(Draft).where(Draft.id == draft_id).options(selectinload(Draft.picks))
    )
    assignments = {pick.id: "pos_1" for pick in draft.picks[:-1]}
    await sqlite_session.commit()
    batru = FakeBatruClient([])

    with pytest.raises(InvalidRoleAssignmentError, match="every pick"):
        await PredictionService(sqlite_session, batru).predict_draft_with_roles(
            draft_id, assignments
        )
    assert batru.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize("map_status", ["unknown", "scheduled", "live", "completed"])
async def test_prediction_does_not_depend_on_map_status_or_actual_result(
    sqlite_session, create_draft, map_status
):
    from app.models import Draft, MatchGame

    draft_id = await create_draft()
    draft = await sqlite_session.get(Draft, draft_id)
    assert draft is not None
    game = await sqlite_session.get(MatchGame, draft.match_game_id)
    assert game is not None
    game.status = map_status
    game.radiant_won = map_status == "completed"
    await sqlite_session.commit()

    batru = FakeBatruClient([prediction()])
    service = PredictionService(sqlite_session, batru, retry_backoff_seconds=0)

    result = await service.predict_draft(draft_id)

    assert result.radiant_probability == Decimal("0.6500000")
    assert len(batru.requests) == 1


@pytest.mark.asyncio
async def test_incomplete_draft_does_not_call_batru(sqlite_session, create_draft):
    draft_id = await create_draft(pick_count=9)
    batru = FakeBatruClient([prediction()])
    service = PredictionService(sqlite_session, batru, retry_backoff_seconds=0)

    with pytest.raises(InvalidDraftError, match="exactly 10 picks"):
        await service.predict_draft(draft_id)

    assert batru.requests == []


@pytest.mark.asyncio
async def test_completed_draft_with_missing_pick_is_rejected(sqlite_session, create_draft):
    draft_id = await create_draft(pick_count=9)
    batru = FakeBatruClient([prediction()])
    service = PredictionService(sqlite_session, batru, retry_backoff_seconds=0)

    with pytest.raises(InvalidDraftError, match="exactly 10 picks"):
        await service.predict_draft(draft_id)

    assert batru.requests == []


@pytest.mark.asyncio
async def test_unverified_mapping_reports_hero_identity_and_skips_batru(
    sqlite_session, create_draft
):
    from sqlalchemy.orm import selectinload

    from app.models import Draft, DraftPick

    draft_id = await create_draft()
    draft = await sqlite_session.scalar(
        select(Draft)
        .where(Draft.id == draft_id)
        .options(selectinload(Draft.picks).selectinload(DraftPick.hero))
    )
    assert draft is not None
    draft.picks[0].hero.name = "Unknown hero 777"
    draft.picks[0].hero.batru_mapping = None
    await sqlite_session.commit()

    batru = FakeBatruClient([])
    service = PredictionService(sqlite_session, batru, retry_backoff_seconds=0)

    with pytest.raises(HeroMappingError, match=r"Unknown hero 777.*opendota:hero-1-0"):
        await service.predict_draft(draft_id)

    assert batru.requests == []


@pytest.mark.asyncio
async def test_temporary_batru_error_is_retried(sqlite_session, create_draft):
    draft_id = await create_draft()
    batru = FakeBatruClient(
        [BatruTemporaryError("temporary"), prediction()],
        session=sqlite_session,
    )
    service = PredictionService(
        sqlite_session,
        batru,
        max_retries=1,
        retry_backoff_seconds=0,
    )

    result = await service.predict_draft(draft_id)

    assert result.radiant_probability == Decimal("0.6500000")
    assert len(batru.requests) == 2


@pytest.mark.asyncio
async def test_inconsistent_probabilities_are_not_persisted(
    sqlite_session, create_draft
):
    draft_id = await create_draft()
    batru = FakeBatruClient([prediction("0.7", "0.35")])
    service = PredictionService(sqlite_session, batru, retry_backoff_seconds=0)

    with pytest.raises(PredictionResponseError, match="inconsistent"):
        await service.predict_draft(draft_id)

    assert await sqlite_session.scalar(select(func.count()).select_from(Prediction)) == 0
