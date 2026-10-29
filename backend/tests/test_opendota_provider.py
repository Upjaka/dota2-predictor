import httpx
import pytest

from app.integrations.opendota_errors import (
    OpenDotaInvalidResponseError,
    OpenDotaTemporaryError,
)
from app.integrations.opendota_provider import OpenDotaProvider


@pytest.mark.asyncio
async def test_pro_matches_normalizes_documented_series_and_map_fields():
    def handler(request):
        assert request.url.path == "/api/proMatches"
        return httpx.Response(
            200,
            json=[
                {
                    "match_id": 9065380598,
                    "series_id": 1160851,
                    "series_type": 1,
                    "start_time": 1793178411,
                    "duration": 3021,
                    "leagueid": 42,
                    "radiant_team_id": 9823272,
                    "radiant_name": "Radiant team",
                    "dire_team_id": 9964962,
                    "dire_name": "Dire team",
                    "league_name": "Tournament",
                    "radiant_win": True,
                    "radiant_score": 30,
                    "dire_score": 22,
                },
                {
                    "match_id": 9065380599,
                    "series_id": 1160851,
                    "series_type": 1,
                    "radiant_team_id": 9823272,
                    "dire_team_id": 9964962,
                },
            ],
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        matches = await OpenDotaProvider(
            base_url="https://api.opendota.com/api",
            max_retries=0,
            http_client=http,
        ).get_current_matches()

    assert len(matches) == 2
    assert matches[0].provider_match_id == "9065380598"
    assert matches[0].provider_series_id == "1160851"
    assert matches[0].series_type == 1
    assert matches[0].league_id == "42"
    assert matches[0].map is not None
    assert matches[0].map.status == "completed"
    assert matches[0].map.radiant_won is True
    assert matches[0].map.radiant_score == 30
    assert matches[0].map.dire_score == 22
    assert matches[1].map is not None
    assert matches[1].map.status is None
    assert matches[1].map.radiant_won is None


@pytest.mark.asyncio
async def test_pro_matches_rejects_winner_that_conflicts_with_final_scores():
    def handler(_request):
        return httpx.Response(
            200,
            json=[
                {
                    "match_id": 9065380598,
                    "series_id": 1160851,
                    "radiant_team_id": 9823272,
                    "dire_team_id": 9964962,
                    "duration": 3021,
                    "radiant_win": True,
                    "radiant_score": 18,
                    "dire_score": 24,
                }
            ],
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        matches = await OpenDotaProvider(max_retries=0, http_client=http).get_current_matches()

    assert matches[0].map is not None
    assert matches[0].map.status == "completed"
    assert matches[0].map.radiant_won is None
    assert matches[0].map.radiant_score == 18
    assert matches[0].map.dire_score == 24


@pytest.mark.asyncio
async def test_live_feed_normalizes_professional_game_and_rejects_non_live_records():
    def handler(request):
        assert request.url.path == "/api/live"
        return httpx.Response(
            200,
            json=[
                {
                    "match_id": "9065653541",
                    "series_id": 1160918,
                    "league_id": 20395,
                    "team_id_radiant": 10292107,
                    "team_name_radiant": "Astra Invicta",
                    "team_id_dire": 9823272,
                    "team_name_dire": "Team Yandex",
                    "activate_time": 1793194643,
                    "deactivate_time": 0,
                    "last_update_time": 1793196800,
                    "game_time": 1800,
                    "players": [
                        {"hero_id": 109, "team": 0, "team_slot": 1},
                        {"hero_id": 119, "team": 0, "team_slot": 2},
                        {"hero_id": 49, "team": 0, "team_slot": 3},
                        {"hero_id": 56, "team": 0, "team_slot": 4},
                        {"hero_id": 93, "team": 0, "team_slot": 5},
                        {"hero_id": 50, "team": 1, "team_slot": 1},
                        {"hero_id": 123, "team": 1, "team_slot": 2},
                        {"hero_id": 36, "team": 1, "team_slot": 3},
                        {"hero_id": 7, "team": 1, "team_slot": 4},
                        {"hero_id": 121, "team": 1, "team_slot": 5},
                    ],
                },
                {
                    "match_id": "9065511384",
                    "series_id": 1160851,
                    "league_id": 20395,
                    "team_id_radiant": 9824702,
                    "team_name_radiant": "PARIVISION",
                    "team_id_dire": 2163,
                    "team_name_dire": "Team Liquid",
                    "activate_time": 1793188102,
                    "deactivate_time": 1793193100,
                },
                {
                    "match_id": "9065502789",
                    "series_id": 0,
                    "league_id": 0,
                    "team_id_radiant": 0,
                    "team_name_radiant": "",
                    "team_id_dire": 0,
                    "team_name_dire": "",
                    "activate_time": 1793186556,
                    "deactivate_time": 0,
                },
                {"match_id": "malformed"},
            ],
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        matches = await OpenDotaProvider(
            base_url="https://api.opendota.com/api",
            max_retries=0,
            http_client=http,
        ).get_live_matches()

    assert len(matches) == 1
    match = matches[0]
    assert match.provider_match_id == "9065653541"
    assert match.provider_series_id == "1160918"
    assert match.league_id == "20395"
    assert match.radiant_team.external_team_id == "10292107"
    assert match.radiant_team.name == "Astra Invicta"
    assert match.dire_team.external_team_id == "9823272"
    assert match.dire_team.name == "Team Yandex"
    assert match.map is not None
    assert match.map.external_game_id == "9065653541"
    assert match.map.started_at.isoformat() == "2026-10-28T13:37:23+00:00"
    assert match.map.status == "live"
    assert match.map.duration_seconds is None
    assert match.map.radiant_won is None
    assert match.map.draft is not None
    assert match.map.draft.pick_order_is_chronological is False
    assert len(match.map.draft.picks) == 10
    assert match.map.draft.picks[0].external_hero_id == "109"
    assert match.map.draft.picks[0].side == "radiant"
    assert match.map.draft.picks[-1].external_hero_id == "121"
    assert match.map.draft.picks[-1].side == "dire"


@pytest.mark.asyncio
async def test_live_feed_normalizes_partial_draft_and_ignores_invalid_players():
    def handler(_request):
        return httpx.Response(
            200,
            json=[
                {
                    "match_id": "9065653541",
                    "series_id": 1160918,
                    "league_id": 20395,
                    "team_id_radiant": 10292107,
                    "team_id_dire": 9823272,
                    "players": [
                        {"hero_id": 109, "team": 0, "team_slot": 1},
                        {"hero_id": 0, "team": 0, "team_slot": 2},
                        {"hero_id": 119, "team": 1, "team_slot": 1},
                        {"hero_id": 50, "team": 3, "team_slot": 3},
                        {"team": 1, "team_slot": 4},
                    ],
                }
            ],
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        matches = await OpenDotaProvider(max_retries=0, http_client=http).get_live_matches()

    draft = matches[0].map.draft
    assert draft is not None
    assert draft.pick_order_is_chronological is False
    assert [(pick.external_hero_id, pick.side) for pick in draft.picks] == [
        ("109", "radiant"),
        ("119", "dire"),
    ]


@pytest.mark.asyncio
async def test_hero_directory_returns_verified_image_url_from_canonical_hero_key():
    def handler(request):
        assert request.url.path == "/api/heroes"
        return httpx.Response(
            200,
            json=[
                {
                    "id": 1,
                    "name": "npc_dota_hero_antimage",
                    "localized_name": "Anti-Mage",
                },
                {
                    "id": 2,
                    "name": "unexpected format",
                    "localized_name": "Unknown",
                },
            ],
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        heroes = await OpenDotaProvider(max_retries=0, http_client=http).get_hero_directory()

    assert heroes[0].image_url == (
        "https://cdn.cloudflare.steamstatic.com/apps/dota2/images/"
        "dota_react/heroes/antimage.png"
    )
    assert heroes[1].image_url is None


@pytest.mark.asyncio
async def test_live_feed_rejects_non_list_response():
    def handler(_request):
        return httpx.Response(200, json={"matches": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        provider = OpenDotaProvider(
            max_retries=0,
            http_client=http,
        )
        with pytest.raises(
            OpenDotaInvalidResponseError, match="live response must be a list"
        ):
            await provider.get_live_matches()


@pytest.mark.asyncio
async def test_live_feed_reports_provider_http_failures():
    def handler(_request):
        return httpx.Response(503)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        provider = OpenDotaProvider(
            max_retries=0,
            http_client=http,
        )
        with pytest.raises(OpenDotaTemporaryError, match="HTTP 503"):
            await provider.get_live_matches()


@pytest.mark.asyncio
async def test_live_feed_reports_provider_timeouts():
    def handler(_request):
        raise httpx.ReadTimeout("request timed out")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        provider = OpenDotaProvider(
            max_retries=0,
            http_client=http,
        )
        with pytest.raises(OpenDotaTemporaryError, match="Could not reach OpenDota"):
            await provider.get_live_matches()
