from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.exc import OperationalError, ProgrammingError

from app.models import Match, MatchGame, Team
from app.repositories.matches import MatchRepository
from app.api.routes.matches import _serialize_game


@pytest.mark.asyncio
async def test_health_endpoint_reports_database_success(api_client):
    response = await api_client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


@pytest.mark.asyncio
async def test_match_list_rejects_limit_above_api_contract(api_client):
    response = await api_client.get("/api/v1/matches?limit=101")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query",
    [
        "status=in_progress",
        "status=provider_future_state",
        "tournament_id=%20",
        f"tournament_id={'x' * 201}",
    ],
)
async def test_match_list_rejects_unsupported_filter_values(api_client, query):
    response = await api_client.get(f"/api/v1/matches?{query}")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


@pytest.mark.asyncio
async def test_match_detail_rejects_invalid_uuid(api_client):
    response = await api_client.get("/api/v1/matches/not-a-uuid")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


@pytest.mark.asyncio
async def test_match_list_reports_connection_errors_as_service_unavailable(
    api_client, monkeypatch
):
    async def fail_to_connect(*args, **kwargs):
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))

    monkeypatch.setattr(MatchRepository, "list_matches", fail_to_connect)
    response = await api_client.get("/api/v1/matches")

    assert response.status_code == 503
    assert response.json()["error"] == {
        "code": "database_unavailable",
        "message": "Database unavailable.",
    }


@pytest.mark.asyncio
async def test_match_list_passes_filter_and_pagination_parameters_to_repository(
    api_client, monkeypatch
):
    received = {}

    async def list_matches(_repository, **kwargs):
        received.update(kwargs)
        return [], 0

    monkeypatch.setattr(MatchRepository, "list_matches", list_matches)
    response = await api_client.get(
        "/api/v1/matches?status=completed&tournament_id=42&offset=10&limit=5&sort_order=desc"
    )

    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0, "offset": 10, "limit": 5}
    assert received == {
        "status": "completed",
        "tournament_id": "42",
        "offset": 10,
        "limit": 5,
        "sort_order": "desc",
    }


@pytest.mark.asyncio
async def test_tournament_endpoint_returns_stable_identifier_and_name(api_client, monkeypatch):
    async def list_tournaments(_repository):
        return [("42", "Autumn Cup")]

    monkeypatch.setattr(MatchRepository, "list_tournaments", list_tournaments)
    response = await api_client.get("/api/v1/matches/tournaments")

    assert response.status_code == 200
    assert response.json() == [{"id": "42", "name": "Autumn Cup"}]


@pytest.mark.asyncio
async def test_match_list_returns_live_match_from_repository(api_client, monkeypatch):
    radiant = Team(
        id=uuid4(),
        provider="opendota",
        external_team_id="10292107",
        name="Astra Invicta",
    )
    dire = Team(
        id=uuid4(),
        provider="opendota",
        external_team_id="9823272",
        name="Team Yandex",
    )
    match = Match(
        id=uuid4(),
        provider="opendota",
        external_match_id="series:1160918",
        team_one=dire,
        team_two=radiant,
        status="live",
        league_name="PARI UNIVERSE by FISSURE",
        league_id="20395",
        received_at=datetime(2026, 10, 28, 14, 0, tzinfo=timezone.utc),
    )

    async def list_matches(_repository, **kwargs):
        assert kwargs["status"] == "live"
        assert kwargs["tournament_id"] == "20395"
        return [(match, datetime(2026, 10, 28, 13, 37, 23, tzinfo=timezone.utc))], 1

    monkeypatch.setattr(MatchRepository, "list_matches", list_matches)
    response = await api_client.get(
        "/api/v1/matches?status=live&tournament_id=20395"
    )

    assert response.status_code == 200
    result = response.json()
    assert result["total"] == 1
    assert result["items"][0]["status"] == "live"
    assert result["items"][0]["external_match_id"] == "series:1160918"
    assert result["items"][0]["team_one"]["name"] == "Team Yandex"
    assert result["items"][0]["team_two"]["name"] == "Astra Invicta"
    assert result["items"][0]["league_name"] == "PARI UNIVERSE by FISSURE"


@pytest.mark.parametrize(
    ("radiant_won", "expected_side", "expected_team_name"),
    [
        (True, "radiant", "Radiant team"),
        (False, "dire", "Dire team"),
    ],
)
def test_completed_game_serializes_map_winner_from_provider_result(
    radiant_won, expected_side, expected_team_name
):
    radiant = Team(
        id=uuid4(),
        provider="opendota",
        external_team_id="1",
        name="Radiant team",
    )
    dire = Team(
        id=uuid4(),
        provider="opendota",
        external_team_id="2",
        name="Dire team",
    )
    game = MatchGame(
        id=uuid4(),
        match_id=uuid4(),
        game_number=1,
        provider="opendota",
        status="completed",
        radiant_won=radiant_won,
        radiant_score=30 if radiant_won else 20,
        dire_score=20 if radiant_won else 30,
        radiant_team_id=radiant.id,
        dire_team_id=dire.id,
        radiant_team=radiant,
        dire_team=dire,
    )

    result = _serialize_game(game)

    assert result.winner_side == expected_side
    assert result.winner_team_name == expected_team_name
    assert result.winner_team_id == (
        radiant.id if radiant_won else dire.id
    )
    assert result.radiant_team.name == "Radiant team"
    assert result.dire_team.name == "Dire team"


def test_game_winner_is_unknown_for_live_or_contradictory_result():
    radiant = Team(
        id=uuid4(),
        provider="opendota",
        external_team_id="1",
        name="Radiant team",
    )
    dire = Team(
        id=uuid4(),
        provider="opendota",
        external_team_id="2",
        name="Dire team",
    )
    game = MatchGame(
        id=uuid4(),
        match_id=uuid4(),
        game_number=1,
        provider="opendota",
        status="live",
        radiant_won=True,
        radiant_score=10,
        dire_score=20,
        radiant_team_id=radiant.id,
        dire_team_id=dire.id,
        radiant_team=radiant,
        dire_team=dire,
    )

    assert _serialize_game(game).winner_side == "unknown"
    game.status = "completed"
    assert _serialize_game(game).winner_side == "unknown"
    game.radiant_won = None
    game.radiant_score = None
    game.dire_score = None
    assert _serialize_game(game).winner_side == "unknown"


@pytest.mark.asyncio
async def test_game_draft_response_includes_partial_picks_and_hero_portraits(
    api_client, monkeypatch
):
    game_id = uuid4()
    draft = SimpleNamespace(
        id=uuid4(),
        match_game_id=game_id,
        version=1,
        received_at=datetime(2026, 10, 28, 14, 0, tzinfo=timezone.utc),
        completed_at=datetime(2026, 10, 28, 15, 0, tzinfo=timezone.utc),
        pick_order_is_chronological=False,
        picks=[
            SimpleNamespace(
                id=uuid4(),
                hero_id=uuid4(),
                hero=SimpleNamespace(
                    name="Anti-Mage",
                    image_url="https://cdn.example/antimage.png",
                    provider="opendota",
                    external_hero_id="1",
                ),
                side="radiant",
                position="unknown",
                pick_order=1,
            )
        ],
    )

    async def get_latest_draft(_repository, requested_game_id):
        assert requested_game_id == game_id
        return True, draft

    monkeypatch.setattr(MatchRepository, "get_latest_draft", get_latest_draft)
    response = await api_client.get(f"/api/v1/games/{game_id}/draft")

    assert response.status_code == 200
    result = response.json()
    assert result["completed_at"] is not None
    assert result["is_complete"] is False
    assert result["pick_order_is_chronological"] is False
    assert len(result["picks"]) == 1
    assert result["picks"][0]["side"] == "radiant"
    assert result["picks"][0]["hero_name"] == "Anti-Mage"
    assert result["picks"][0]["hero_image_url"] == "https://cdn.example/antimage.png"
    assert result["picks"][0]["pick_order"] is None


@pytest.mark.asyncio
async def test_game_draft_returns_not_found_when_no_draft_is_available(
    api_client, monkeypatch
):
    async def get_latest_draft(_repository, _game_id):
        return True, None

    monkeypatch.setattr(MatchRepository, "get_latest_draft", get_latest_draft)
    response = await api_client.get(f"/api/v1/games/{uuid4()}/draft")

    assert response.status_code == 404
    assert response.json()["error"]["message"] == "Draft not found for this game."


@pytest.mark.asyncio
async def test_game_draft_response_preserves_completed_ten_hero_lineup(
    api_client, monkeypatch
):
    game_id = uuid4()
    draft = SimpleNamespace(
        id=uuid4(),
        match_game_id=game_id,
        version=2,
        received_at=datetime(2026, 10, 28, 14, 0, tzinfo=timezone.utc),
        completed_at=None,
        pick_order_is_chronological=True,
        picks=[
            SimpleNamespace(
                id=uuid4(),
                hero_id=uuid4(),
                hero=SimpleNamespace(
                    name=f"Hero {index}",
                    image_url=f"https://cdn.example/hero-{index}.png",
                    provider="opendota",
                    external_hero_id=str(index),
                ),
                side="radiant" if index < 5 else "dire",
                position="unknown",
                pick_order=index + 1,
            )
            for index in range(10)
        ],
    )

    async def get_latest_draft(_repository, _game_id):
        return True, draft

    monkeypatch.setattr(MatchRepository, "get_latest_draft", get_latest_draft)
    response = await api_client.get(f"/api/v1/games/{game_id}/draft")

    assert response.status_code == 200
    result = response.json()
    assert result["completed_at"] is None
    assert result["is_complete"] is True
    assert result["pick_order_is_chronological"] is True
    assert len(result["picks"]) == 10
    assert sum(pick["side"] == "radiant" for pick in result["picks"]) == 5
    assert sum(pick["side"] == "dire" for pick in result["picks"]) == 5
    assert all(pick["hero_image_url"] for pick in result["picks"])


@pytest.mark.asyncio
async def test_match_list_does_not_report_query_errors_as_database_unavailable(
    api_client, monkeypatch
):
    async def fail_query(*args, **kwargs):
        raise ProgrammingError(
            "SELECT * FROM matches",
            {},
            Exception("relation matches does not exist"),
        )

    monkeypatch.setattr(MatchRepository, "list_matches", fail_query)
    response = await api_client.get("/api/v1/matches")

    assert response.status_code == 500
    assert response.json()["error"] == {
        "code": "database_error",
        "message": "A database error occurred.",
    }
    assert "relation matches does not exist" not in response.text


@pytest.mark.asyncio
async def test_dashboard_returns_compact_current_map_draft_and_prediction_state(
    api_client, monkeypatch
):
    team_one = Team(
        id=uuid4(), provider="opendota", external_team_id="team-1", name="Radiant"
    )
    team_two = Team(
        id=uuid4(), provider="opendota", external_team_id="team-2", name="Dire"
    )
    match_id = uuid4()
    game_id = uuid4()
    draft_id = uuid4()
    match = Match(
        id=match_id,
        provider="opendota",
        external_match_id="series-1",
        team_one=team_one,
        team_two=team_two,
        status="live",
        league_name="Autumn Cup",
        league_id="42",
        format="BO3",
        received_at=datetime(2026, 10, 28, tzinfo=timezone.utc),
    )
    match_without_draft = Match(
        id=uuid4(),
        provider="opendota",
        external_match_id="series-2",
        team_one=team_one,
        team_two=team_two,
        status="live",
        league_name="Autumn Cup",
        league_id="42",
        format="BO3",
        received_at=datetime(2026, 10, 28, tzinfo=timezone.utc),
    )
    match_without_game = Match(
        id=uuid4(),
        provider="opendota",
        external_match_id="series-3",
        team_one=team_one,
        team_two=team_two,
        status="scheduled",
        league_name="Autumn Cup",
        league_id="42",
        format="BO3",
        received_at=datetime(2026, 10, 28, tzinfo=timezone.utc),
    )
    game = MatchGame(
        id=game_id,
        match_id=match_id,
        game_number=2,
        provider="opendota",
        external_game_id="map-2",
        status="completed",
        radiant_won=True,
        radiant_score=30,
        dire_score=20,
        radiant_team_id=team_one.id,
        dire_team_id=team_two.id,
        radiant_team=team_one,
        dire_team=team_two,
    )
    game_without_draft = MatchGame(
        id=uuid4(),
        match_id=match_without_draft.id,
        game_number=1,
        provider="opendota",
        external_game_id="map-without-draft",
        status="live",
        radiant_team_id=team_one.id,
        dire_team_id=team_two.id,
        radiant_team=team_one,
        dire_team=team_two,
    )
    picks = [
        SimpleNamespace(
            hero_id=uuid4(),
            side="radiant" if index < 5 else "dire",
            hero=SimpleNamespace(
                provider="opendota", external_hero_id=f"hero-{index}"
            ),
        )
        for index in range(10)
    ]
    draft = SimpleNamespace(
        id=draft_id,
        match_game_id=game_id,
        version=3,
        pick_order_is_chronological=False,
        picks=picks,
    )
    job = SimpleNamespace(draft_id=draft_id, status="succeeded")
    received = {}

    async def get_dashboard_data(_repository, **kwargs):
        received.update(kwargs)
        return (
            [
                (match, datetime(2026, 10, 28, tzinfo=timezone.utc)),
                (match_without_draft, datetime(2026, 10, 28, tzinfo=timezone.utc)),
                (match_without_game, None),
            ],
            3,
            [("42", "Autumn Cup")],
            {match_id: game, match_without_draft.id: game_without_draft},
            {game_id: draft},
            {draft_id},
            {draft_id: job},
        )

    monkeypatch.setattr(MatchRepository, "get_dashboard_data", get_dashboard_data)
    response = await api_client.get(
        "/api/v1/matches/dashboard?status=live&tournament_id=42&offset=10&limit=5&sort_order=desc"
    )

    assert response.status_code == 200
    result = response.json()
    assert result["total"] == 3
    assert result["offset"] == 10
    assert result["limit"] == 5
    assert result["tournaments"] == [{"id": "42", "name": "Autumn Cup"}]
    assert len(result["items"]) == 3
    item = result["items"][0]
    assert item["current_game"]["id"] == str(game_id)
    assert item["current_game"]["winner_side"] == "radiant"
    assert item["current_game"]["winner_team_name"] == "Radiant"
    assert item["draft"] == {
        "version": 3,
        "pick_count": 10,
        "is_complete": True,
        "pick_order_is_chronological": False,
    }
    assert item["has_prediction"] is True
    assert item["prediction_job_status"] == "succeeded"
    assert result["items"][1]["current_game"] is not None
    assert result["items"][1]["draft"] is None
    assert result["items"][1]["has_prediction"] is False
    assert result["items"][1]["prediction_job_status"] is None
    assert result["items"][2]["current_game"] is None
    assert result["items"][2]["draft"] is None
    assert received == {
        "status": "live",
        "tournament_id": "42",
        "offset": 10,
        "limit": 5,
        "sort_order": "desc",
    }
