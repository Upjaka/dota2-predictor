from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.models import Match, MatchGame, Team
from app.repositories.matches import MatchRepository


@pytest.mark.asyncio
async def test_match_filters_apply_before_pagination_and_keep_series_unique(sqlite_session):
    team_one = Team(provider="test", external_team_id="one", name="Team One")
    team_two = Team(provider="test", external_team_id="two", name="Team Two")
    matches = [
        Match(
            provider="test",
            external_match_id="series-1",
            team_one=team_one,
            team_two=team_two,
            status="completed",
            league_id="league-1",
            league_name="Autumn Cup",
        ),
        Match(
            provider="test",
            external_match_id="series-2",
            team_one=team_one,
            team_two=team_two,
            status="completed",
            league_id="league-1",
            league_name="Autumn Cup",
        ),
        Match(
            provider="test",
            external_match_id="series-3",
            team_one=team_one,
            team_two=team_two,
            status="unknown",
            league_id="league-2",
            league_name="Winter Cup",
        ),
        Match(
            provider="test",
            external_match_id="series-4",
            team_one=team_one,
            team_two=team_two,
            status="unknown",
        ),
        Match(
            provider="test",
            external_match_id="series-5",
            team_one=team_one,
            team_two=team_two,
            status="scheduled",
        ),
        Match(
            provider="test",
            external_match_id="series-live",
            team_one=team_one,
            team_two=team_two,
            status="live",
            league_id="league-1",
            league_name="Autumn Cup",
        ),
    ]
    for index, match in enumerate(matches):
        match.games.append(
            MatchGame(
                game_number=1,
                provider="test",
                external_game_id=f"game-{index}-1",
                started_at=datetime(2026, 1, index + 1, tzinfo=timezone.utc),
            )
        )
    matches[0].games.append(
        MatchGame(
            game_number=2,
            provider="test",
            external_game_id="game-0-2",
            started_at=datetime(2026, 1, 5, tzinfo=timezone.utc),
        )
    )
    sqlite_session.add_all(matches)
    await sqlite_session.flush()
    repository = MatchRepository(sqlite_session)

    all_rows, all_total = await repository.list_matches(
        status=None, offset=0, limit=20, sort_order="asc"
    )
    assert all_total == 6
    assert len(all_rows) == 6

    completed, completed_total = await repository.list_matches(
        status="completed", offset=0, limit=20, sort_order="asc"
    )
    assert completed_total == 2
    assert {row.external_match_id for row, _ in completed} == {"series-1", "series-2"}

    unknown, unknown_total = await repository.list_matches(
        status="unknown", offset=0, limit=20, sort_order="asc"
    )
    assert unknown_total == 2
    assert {row.external_match_id for row, _ in unknown} == {"series-3", "series-4"}

    scheduled, scheduled_total = await repository.list_matches(
        status="scheduled", offset=0, limit=20, sort_order="asc"
    )
    assert scheduled_total == 1
    assert scheduled[0][0].external_match_id == "series-5"

    live, live_total = await repository.list_matches(
        status="live", offset=0, limit=20, sort_order="asc"
    )
    assert live_total == 1
    assert live[0][0].external_match_id == "series-live"

    tournament, tournament_total = await repository.list_matches(
        status=None,
        tournament_id="league-1",
        offset=0,
        limit=20,
        sort_order="asc",
    )
    assert tournament_total == 3
    assert len(tournament) == 3

    combined, combined_total = await repository.list_matches(
        status="completed",
        tournament_id="league-1",
        offset=1,
        limit=1,
        sort_order="desc",
    )
    assert combined_total == 2
    assert len(combined) == 1
    assert combined[0][0].external_match_id == "series-1"

    tournaments = await repository.list_tournaments()
    assert tournaments == [
        ("league-1", "Autumn Cup"),
        ("league-2", "Winter Cup"),
    ]
    assert await sqlite_session.scalar(
        select(Match.id).where(Match.external_match_id == "series-4")
    )
