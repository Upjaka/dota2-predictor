import pytest

from app.models import Match, Team
from app.services.match_status import status_from_series_score


@pytest.mark.parametrize(
    ("current_status", "series_format", "team_one_wins", "team_two_wins", "expected"),
    [
        ("unknown", "BO3", 1, 0, "unknown"),
        ("unknown", "BO3", 2, 0, "completed"),
        ("unknown", "BO5", 2, 2, "unknown"),
        ("unknown", "BO5", 3, 1, "completed"),
        ("unknown", None, 1, 0, "unknown"),
        ("unknown", "unrecognized", 9, 0, "unknown"),
        ("completed", "BO3", 0, 0, "completed"),
        ("scheduled", "BO3", 1, 1, "scheduled"),
        ("live", "BO3", 2, 0, "completed"),
    ],
)
def test_status_is_completed_only_after_a_series_winning_score(
    current_status,
    series_format,
    team_one_wins,
    team_two_wins,
    expected,
):
    assert (
        status_from_series_score(
            current_status,
            series_format,
            team_one_wins,
            team_two_wins,
        )
        == expected
    )


@pytest.mark.asyncio
async def test_new_series_defaults_to_unknown(sqlite_session):
    match = Match(
        provider="test",
        external_match_id="series-without-source-status",
        team_one=Team(
            provider="test",
            external_team_id="team-one",
            name="Team One",
        ),
        team_two=Team(
            provider="test",
            external_team_id="team-two",
            name="Team Two",
        ),
    )
    sqlite_session.add(match)
    await sqlite_session.flush()

    assert match.status == "unknown"
