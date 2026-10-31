import json

import httpx
import pytest

from app.integrations.batru_client import BatruClient
from app.integrations.batru_errors import (
    BatruInvalidResponseError,
    BatruRateLimitedError,
    BatruTemporaryError,
)
from app.integrations.interfaces import BatruHero, Draft


def sample_draft():
    return Draft(
        radiant_heroes=("axe", "bane", "chen", "drow", "earthshaker"),
        dire_heroes=("abaddon", "alchemist", "ancient_apparition", "antimage", "arc_warden"),
    )


@pytest.mark.asyncio
async def test_prediction_request_uses_batru_contract_and_normalizes_percentages():
    def handler(request):
        assert request.url.path == "/api/winrate"
        assert json.loads(request.read()) == {
            "radiant": ["axe", "bane", "chen", "drow", "earthshaker"],
            "dire": [
                "abaddon",
                "alchemist",
                "ancient_apparition",
                "antimage",
                "arc_warden",
            ],
        }
        return httpx.Response(
            200,
            json={"radiant_win_rate": 62.5, "dire_win_rate": 37.5},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await BatruClient(http_client=http).predict_draft(sample_draft())

    assert str(result.radiant_probability) == "0.625"
    assert str(result.dire_probability) == "0.375"


@pytest.mark.asyncio
async def test_role_aware_request_sends_role_arrays_aligned_with_heroes():
    def handler(request):
        assert json.loads(request.read()) == {
            "radiant": ["axe", "bane", "chen", "drow", "earthshaker"],
            "dire": ["abaddon", "alchemist", "ancient_apparition", "antimage", "arc_warden"],
            "radiant_roles": [1, 2, 3, 4, 5],
            "dire_roles": [5, 4, 3, 2, 1],
        }
        return httpx.Response(200, json={"radiant_win_rate": 62.5, "dire_win_rate": 37.5})

    draft = Draft(
        radiant_heroes=sample_draft().radiant_heroes,
        dire_heroes=sample_draft().dire_heroes,
        radiant_roles=(1, 2, 3, 4, 5),
        dire_roles=(5, 4, 3, 2, 1),
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await BatruClient(http_client=http).predict_draft(draft)

    assert str(result.radiant_probability) == "0.625"


@pytest.mark.asyncio
async def test_rate_limit_is_reported_as_retryable_with_retry_after():
    def handler(_request):
        return httpx.Response(429, headers={"Retry-After": "3"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(BatruRateLimitedError) as error:
            await BatruClient(http_client=http).predict_draft(sample_draft())

    assert error.value.retry_after == 3


@pytest.mark.asyncio
async def test_invalid_batru_response_is_not_treated_as_success():
    def handler(_request):
        return httpx.Response(200, json={"radiant_win_rate": 70})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(BatruInvalidResponseError):
            await BatruClient(http_client=http).predict_draft(sample_draft())


@pytest.mark.asyncio
async def test_server_error_is_reported_as_retryable():
    def handler(_request):
        return httpx.Response(503)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(BatruTemporaryError, match="503"):
            await BatruClient(http_client=http).predict_draft(sample_draft())


@pytest.mark.asyncio
async def test_invalid_json_and_timeout_are_reported_without_success_fallbacks():
    async def invalid_json(_request):
        return httpx.Response(200, content=b"not json")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(invalid_json)
    ) as http:
        with pytest.raises(BatruInvalidResponseError):
            await BatruClient(http_client=http).predict_draft(sample_draft())

    async def timeout(_request):
        raise httpx.ReadTimeout("request timed out")

    async with httpx.AsyncClient(transport=httpx.MockTransport(timeout)) as http:
        with pytest.raises(BatruTemporaryError, match="Could not reach Batru"):
            await BatruClient(http_client=http).predict_draft(sample_draft())


@pytest.mark.asyncio
async def test_hero_directory_uses_stable_ids_and_verified_short_names():
    def handler(request):
        assert request.method == "GET"
        assert request.url.path == "/api/data/heroes"
        return httpx.Response(
            200,
            json={
                "constants": {
                    "heroes": [
                        {
                            "id": 1,
                            "name": "npc_dota_hero_antimage",
                            "displayName": "Anti-Mage",
                            "shortName": "antimage",
                            "aliases": ["am"],
                        },
                        {
                            "id": 2,
                            "name": "npc_dota_hero_axe",
                            "displayName": "Axe",
                            "shortName": "axe",
                            "aliases": [],
                        },
                    ]
                }
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        heroes = await BatruClient(http_client=http).get_hero_directory()

    assert heroes == (
        BatruHero(
            external_hero_id="1",
            canonical_name="npc_dota_hero_antimage",
            display_name="Anti-Mage",
            short_name="antimage",
        ),
        BatruHero(
            external_hero_id="2",
            canonical_name="npc_dota_hero_axe",
            display_name="Axe",
            short_name="axe",
        ),
    )


@pytest.mark.asyncio
async def test_duplicate_or_invalid_batru_hero_directory_is_rejected():
    def handler(_request):
        return httpx.Response(
            200,
            json={
                "constants": {
                    "heroes": [
                        {
                            "id": 1,
                            "name": "npc_dota_hero_antimage",
                            "displayName": "Anti-Mage",
                            "shortName": "antimage",
                        },
                        {
                            "id": 2,
                            "name": "npc_dota_hero_axe",
                            "displayName": "Axe",
                            "shortName": "antimage",
                        },
                    ]
                }
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(BatruInvalidResponseError, match="duplicate"):
            await BatruClient(http_client=http).get_hero_directory()
