from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import event

from decimal import Decimal

from app.models import Draft, DraftPick, Hero, Match, MatchGame, Prediction, PredictionJob, Team
from app.repositories.matches import MatchRepository
from app.repositories.matches import _select_current_game


async def test_dashboard_database_query_count_does_not_grow_with_page_size(
    sqlite_session_factory,
):
    team_one = Team(provider="test", external_team_id="dashboard-one", name="One")
    team_two = Team(provider="test", external_team_id="dashboard-two", name="Two")
    hero = Hero(provider="test", external_hero_id="dashboard-hero", name="Hero")

    async with sqlite_session_factory() as session:
        for index in range(20):
            match = Match(
                provider="test",
                external_match_id=f"dashboard-series-{index}",
                team_one=team_one,
                team_two=team_two,
                status="live",
                league_id="dashboard-league",
                league_name="Dashboard League",
            )
            game = MatchGame(
                match=match,
                game_number=1,
                provider="test",
                external_game_id=f"dashboard-game-{index}",
                started_at=datetime(2026, 10, 31, tzinfo=timezone.utc),
                status="live",
                radiant_team=team_one,
                dire_team=team_two,
            )
            game.drafts.append(
                Draft(
                    version=1,
                    picks=[
                        DraftPick(
                            hero=hero,
                            side="radiant",
                            pick_order=1,
                        )
                    ],
                )
            )
            session.add(match)
        await session.commit()

    engine = sqlite_session_factory.kw["bind"].sync_engine
    query_count = 0

    def count_query(*_args):
        nonlocal query_count
        query_count += 1

    event.listen(engine, "before_cursor_execute", count_query)
    try:
        async with sqlite_session_factory() as session:
            repository = MatchRepository(session)
            await repository.get_dashboard_data(
                status=None,
                tournament_id=None,
                offset=0,
                limit=1,
                sort_order="desc",
            )
            single_match_query_count = query_count

            query_count = 0
            await repository.get_dashboard_data(
                status=None,
                tournament_id=None,
                offset=0,
                limit=20,
                sort_order="desc",
            )
            twenty_match_query_count = query_count
    finally:
        event.remove(engine, "before_cursor_execute", count_query)

    assert single_match_query_count == twenty_match_query_count
    assert twenty_match_query_count == 8


async def test_dashboard_selects_live_game_and_only_its_latest_draft(
    sqlite_session_factory,
):
    team_one = Team(provider="test", external_team_id="latest-one", name="One")
    team_two = Team(provider="test", external_team_id="latest-two", name="Two")
    hero = Hero(provider="test", external_hero_id="latest-hero", name="Hero")
    match = Match(
        provider="test",
        external_match_id="latest-series",
        team_one=team_one,
        team_two=team_two,
        status="live",
    )
    completed_game = MatchGame(
        match=match,
        game_number=2,
        provider="test",
        external_game_id="completed-game",
        started_at=datetime(2026, 10, 30, tzinfo=timezone.utc),
        status="completed",
        radiant_team=team_one,
        dire_team=team_two,
    )
    live_game = MatchGame(
        match=match,
        game_number=1,
        provider="test",
        external_game_id="live-game",
        started_at=datetime(2026, 10, 29, tzinfo=timezone.utc),
        status="live",
        radiant_team=team_one,
        dire_team=team_two,
    )
    older_draft = Draft(
        match_game=live_game,
        version=1,
        picks=[DraftPick(hero=hero, side="radiant", pick_order=1)],
    )
    latest_draft = Draft(
        match_game=live_game,
        version=2,
        picks=[DraftPick(hero=hero, side="radiant", pick_order=1)],
    )
    completed_game.drafts.append(
        Draft(
            version=1,
            picks=[DraftPick(hero=hero, side="radiant", pick_order=1)],
        )
    )

    async with sqlite_session_factory() as session:
        session.add(match)
        await session.flush()
        session.add(
            Prediction(
                draft=older_draft,
                model_name="default",
                radiant_probability=Decimal("0.6000000"),
                dire_probability=Decimal("0.4000000"),
            )
        )
        session.add(
            PredictionJob(
                draft=latest_draft,
                model_name="default",
                status="running",
            )
        )
        await session.commit()
        match_id = match.id
        live_game_id = live_game.id
        latest_draft_id = latest_draft.id

    async with sqlite_session_factory() as session:
        (
            _matches,
            _total,
            _tournaments,
            games_by_match,
            drafts_by_game,
            draft_ids_with_predictions,
            latest_jobs,
        ) = await MatchRepository(session).get_dashboard_data(
            status=None,
            tournament_id=None,
            offset=0,
            limit=20,
            sort_order="desc",
        )

    assert games_by_match[match_id].id == live_game_id
    assert drafts_by_game[live_game_id].version == 2
    assert latest_draft_id not in draft_ids_with_predictions
    assert latest_jobs[latest_draft_id].status == "running"


def test_dashboard_prefers_newest_live_game_when_previous_map_is_stale():
    older_live_game = MatchGame(
        game_number=1,
        started_at=datetime(2026, 11, 1, 10, tzinfo=timezone.utc),
        status="live",
    )
    current_live_game = MatchGame(
        game_number=2,
        started_at=datetime(2026, 11, 1, 11, tzinfo=timezone.utc),
        status="live",
    )

    assert _select_current_game([older_live_game, current_live_game]) is current_live_game
