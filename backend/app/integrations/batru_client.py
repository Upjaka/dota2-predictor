from decimal import Decimal
from typing import Annotated

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.integrations.batru_errors import (
    BatruHTTPError,
    BatruInvalidResponseError,
    BatruRateLimitedError,
    BatruTemporaryError,
)
from app.integrations.interfaces import BatruHero, Draft as BatruDraft, DraftPrediction

ProbabilityPercent = Annotated[Decimal, Field(ge=0, le=100, allow_inf_nan=False)]


class _WinrateResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    radiant_win_rate: ProbabilityPercent
    dire_win_rate: ProbabilityPercent


class _HeroDirectoryEntry(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int = Field(gt=0)
    name: str = Field(min_length=1)
    display_name: str = Field(alias="displayName", min_length=1)
    short_name: str = Field(alias="shortName", min_length=1)


class _HeroDirectoryConstants(BaseModel):
    model_config = ConfigDict(extra="ignore")

    heroes: list[_HeroDirectoryEntry]


class _HeroDirectoryResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    constants: _HeroDirectoryConstants


class BatruClient:
    def __init__(
        self,
        *,
        base_url: str = "https://batru.gg",
        timeout_seconds: float = 8.0,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._url = f"{self._base_url}/api/winrate"
        self._hero_directory_url = f"{self._base_url}/api/data/heroes"
        self._timeout = httpx.Timeout(timeout_seconds, connect=min(timeout_seconds, 3.0))
        self._http_client = http_client

    async def get_hero_directory(self) -> tuple[BatruHero, ...]:
        try:
            if self._http_client is None:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    response = await client.get(
                        self._hero_directory_url,
                        headers={"User-Agent": "Dota2DraftMonitor/0.1"},
                    )
            else:
                response = await self._http_client.get(
                    self._hero_directory_url,
                    timeout=self._timeout,
                    headers={"User-Agent": "Dota2DraftMonitor/0.1"},
                )
        except httpx.TransportError as exc:
            raise BatruTemporaryError("Could not reach Batru hero directory.") from exc

        _raise_for_batru_status(response)
        try:
            result = _HeroDirectoryResponse.model_validate(response.json())
        except (ValueError, ValidationError) as exc:
            raise BatruInvalidResponseError(
                "Batru hero directory did not match its documented format."
            ) from exc

        heroes = result.constants.heroes
        ids = [hero.id for hero in heroes]
        short_names = [hero.short_name.strip() for hero in heroes]
        if (
            not heroes
            or len(ids) != len(set(ids))
            or len(short_names) != len(set(short_names))
            or any(
                not hero.name.strip()
                or not hero.display_name.strip()
                or not hero.short_name.strip()
                for hero in heroes
            )
        ):
            raise BatruInvalidResponseError(
                "Batru hero directory contained empty or duplicate hero identities."
            )

        return tuple(
            BatruHero(
                external_hero_id=str(hero.id),
                canonical_name=hero.name,
                display_name=hero.display_name,
                short_name=hero.short_name.strip(),
            )
            for hero in heroes
        )

    async def predict_draft(self, draft: BatruDraft) -> DraftPrediction:
        payload = {"radiant": list(draft.radiant_heroes), "dire": list(draft.dire_heroes)}
        if draft.radiant_roles is not None and draft.dire_roles is not None:
            payload["radiant_roles"] = list(draft.radiant_roles)
            payload["dire_roles"] = list(draft.dire_roles)
        try:
            if self._http_client is None:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    response = await client.post(
                        self._url,
                        json=payload,
                        headers={"User-Agent": "Dota2DraftMonitor/0.1"},
                    )
            else:
                response = await self._http_client.post(
                    self._url,
                    json=payload,
                    timeout=self._timeout,
                    headers={"User-Agent": "Dota2DraftMonitor/0.1"},
                )
        except httpx.TransportError as exc:
            raise BatruTemporaryError("Could not reach Batru.") from exc

        _raise_for_batru_status(response)

        try:
            result = _WinrateResponse.model_validate(response.json())
        except (ValueError, ValidationError) as exc:
            raise BatruInvalidResponseError(
                "Batru response did not contain valid radiant_win_rate and dire_win_rate percentages."
            ) from exc

        return DraftPrediction(
            radiant_probability=result.radiant_win_rate / Decimal(100),
            dire_probability=result.dire_win_rate / Decimal(100),
        )


def _raise_for_batru_status(response: httpx.Response) -> None:
    if response.status_code == 429:
        raise BatruRateLimitedError(_retry_after_seconds(response))
    if response.status_code == 408 or response.status_code >= 500:
        raise BatruTemporaryError(f"Batru returned HTTP {response.status_code}.")
    if not 200 <= response.status_code < 300:
        raise BatruHTTPError(response.status_code)


def _retry_after_seconds(response: httpx.Response) -> float | None:
    value = response.headers.get("Retry-After")
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None
