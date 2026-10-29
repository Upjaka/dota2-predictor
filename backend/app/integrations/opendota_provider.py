import asyncio
import logging
from collections import Counter
from datetime import datetime, timezone
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from app.core.config import get_settings
from app.integrations.interfaces import (
    MatchSnapshot,
    ProviderDraft,
    ProviderDraftPick,
    ProviderHero,
    ProviderMap,
    ProviderMatchDetails,
    ProviderTeam,
)
from app.integrations.opendota_errors import (
    OpenDotaHTTPError,
    OpenDotaInvalidResponseError,
    OpenDotaRateLimitedError,
    OpenDotaTemporaryError,
)

logger = logging.getLogger(__name__)


class _ProMatchResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    match_id: int = Field(gt=0)
    series_id: int | None = None
    series_type: int | None = None
    start_time: int | None = None
    duration: int | None = None
    leagueid: int | None = None
    radiant_team_id: int | None = None
    radiant_name: str | None = None
    dire_team_id: int | None = None
    dire_name: str | None = None
    league_name: str | None = None
    radiant_win: bool | None = None
    radiant_score: int | None = Field(default=None, ge=0)
    dire_score: int | None = Field(default=None, ge=0)


class _LiveMatchResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    match_id: str = Field(pattern=r"^\d+$")
    series_id: int = Field(default=0, ge=0)
    series_type: int | None = None
    activate_time: int | None = None
    deactivate_time: int = Field(default=0, ge=0)
    league_id: int = Field(default=0, ge=0)
    team_id_radiant: int = Field(default=0, ge=0)
    team_name_radiant: str | None = None
    team_id_dire: int = Field(default=0, ge=0)
    team_name_dire: str | None = None
    players: list[dict[str, Any]] | None = None


class _LivePlayerResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    hero_id: int = Field(ge=0)
    team: int
    team_slot: int = Field(ge=1, le=5)


class _TeamResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    team_id: int | None = None
    name: str | None = None


class _PickBanResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    is_pick: bool
    hero_id: int = Field(gt=0)
    team: int
    order: int = Field(ge=0)


class _HeroResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int = Field(gt=0)
    name: str
    localized_name: str


class _MatchResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    match_id: int = Field(gt=0)
    series_id: int | None = None
    series_type: int | None = None
    start_time: int | None = None
    duration: int | None = None
    radiant_score: int | None = Field(default=None, ge=0)
    dire_score: int | None = Field(default=None, ge=0)
    leagueid: int | None = None
    radiant_win: bool | None = None
    radiant_team_id: int | None = None
    dire_team_id: int | None = None
    radiant_name: str | None = None
    dire_name: str | None = None
    league_name: str | None = None
    radiant_team: _TeamResponse | None = None
    dire_team: _TeamResponse | None = None
    league: dict[str, Any] | None = None
    picks_bans: list[dict[str, Any]] | None = None


class OpenDotaProvider:
    """OpenDota adapter for live professional games and match history."""

    provider_name = "opendota"

    def __init__(
        self,
        *,
        base_url: str = "https://api.opendota.com/api",
        api_key: SecretStr | None = None,
        timeout_seconds: float = 10.0,
        max_retries: int = 2,
        retry_backoff_seconds: float = 0.5,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        if not 0 < timeout_seconds <= 60:
            raise ValueError("timeout_seconds must be greater than 0 and at most 60.")
        if not 0 <= max_retries <= 5:
            raise ValueError("max_retries must be between 0 and 5.")
        if not 0 <= retry_backoff_seconds <= 10:
            raise ValueError("retry_backoff_seconds must be between 0 and 10.")
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = httpx.Timeout(timeout_seconds, connect=min(timeout_seconds, 3.0))
        self._max_retries = max_retries
        self._retry_backoff_seconds = retry_backoff_seconds
        self._http_client = http_client

    @classmethod
    def from_settings(cls) -> "OpenDotaProvider":
        settings = get_settings()
        return cls(
            base_url=settings.opendota_base_url,
            api_key=settings.opendota_api_key,
            timeout_seconds=settings.opendota_timeout_seconds,
            max_retries=settings.opendota_max_retries,
            retry_backoff_seconds=settings.opendota_retry_backoff_seconds,
        )

    async def get_current_matches(
        self, *, less_than_match_id: int | None = None
    ) -> list[MatchSnapshot]:
        """Fetch recent pro match records; this feed is not a live-game feed."""
        params: dict[str, int | str] = {}
        if less_than_match_id is not None:
            if less_than_match_id <= 0:
                raise ValueError("less_than_match_id must be a positive integer.")
            params["less_than_match_id"] = less_than_match_id

        payload = await self._get("/proMatches", params=params)
        if not isinstance(payload, list):
            raise OpenDotaInvalidResponseError("OpenDota pro match response must be a list.")

        matches: list[MatchSnapshot] = []
        for index, item in enumerate(payload):
            try:
                source_match = _ProMatchResponse.model_validate(item)
            except ValidationError:
                logger.warning("Skipping malformed OpenDota pro match at response index %d.", index)
                continue
            matches.append(_normalize_pro_match(source_match))
        return matches

    async def get_live_matches(self) -> list[MatchSnapshot]:
        """Fetch active professional games from OpenDota's live endpoint."""
        payload = await self._get("/live")
        if not isinstance(payload, list):
            raise OpenDotaInvalidResponseError("OpenDota live response must be a list.")

        matches: list[MatchSnapshot] = []
        rejected_reasons: Counter[str] = Counter()
        for index, item in enumerate(payload):
            try:
                source_match = _LiveMatchResponse.model_validate(item)
            except ValidationError:
                logger.warning(
                    "event=live_match_rejected reason=malformed index=%d",
                    index,
                )
                rejected_reasons["malformed"] += 1
                continue

            reason = None
            if source_match.deactivate_time > 0:
                reason = "already_deactivated"
            elif source_match.league_id <= 0:
                reason = "missing_professional_league"
            elif (
                source_match.team_id_radiant <= 0
                or source_match.team_id_dire <= 0
            ):
                reason = "missing_stable_team_ids"
            elif source_match.team_id_radiant == source_match.team_id_dire:
                reason = "duplicate_team_ids"
            if reason:
                rejected_reasons[reason] += 1
                continue

            matches.append(_normalize_live_match(source_match))

        logger.info(
            "event=live_match_feed_normalized provider=%s fetched=%d "
            "accepted=%d rejected=%d rejected_reasons=%s",
            self.provider_name,
            len(payload),
            len(matches),
            sum(rejected_reasons.values()),
            ",".join(
                f"{reason}:{count}"
                for reason, count in sorted(rejected_reasons.items())
            )
            or "none",
        )
        return matches

    async def get_match_details(self, provider_match_id: str) -> ProviderMatchDetails:
        match_id = _parse_match_id(provider_match_id)
        payload = await self._get(f"/matches/{match_id}")
        try:
            source_match = _MatchResponse.model_validate(payload)
        except ValidationError as exc:
            raise OpenDotaInvalidResponseError(
                "OpenDota match response did not match its documented schema."
            ) from exc
        if source_match.match_id != match_id:
            raise OpenDotaInvalidResponseError("OpenDota returned a different match ID.")

        match = _normalize_match(source_match)
        if match.map is None:
            raise OpenDotaInvalidResponseError("OpenDota match details did not normalize to a map.")
        return ProviderMatchDetails(match=match, map=match.map)

    async def get_map_and_draft(self, provider_match_id: str) -> ProviderMap:
        return (await self.get_match_details(provider_match_id)).map

    async def get_match_status(self, provider_match_id: str) -> str | None:
        return (await self.get_match_details(provider_match_id)).map.status

    async def get_hero_directory(self) -> list[ProviderHero]:
        payload = await self._get("/heroes")
        if not isinstance(payload, list):
            raise OpenDotaInvalidResponseError("OpenDota hero response must be a list.")

        heroes: list[ProviderHero] = []
        for index, item in enumerate(payload):
            try:
                source_hero = _HeroResponse.model_validate(item)
            except ValidationError:
                logger.warning("Skipping malformed OpenDota hero at response index %d.", index)
                continue
            heroes.append(
                ProviderHero(
                    external_hero_id=str(source_hero.id),
                    name=source_hero.localized_name,
                    image_url=_hero_image_url(source_hero.name),
                )
            )
        return heroes

    async def _get(
        self,
        path: str,
        *,
        params: dict[str, int | str] | None = None,
    ) -> Any:
        query = dict(params or {})
        if self._api_key is not None and self._api_key.get_secret_value():
            query["api_key"] = self._api_key.get_secret_value()

        for attempt in range(self._max_retries + 1):
            try:
                if self._http_client is None:
                    async with httpx.AsyncClient(timeout=self._timeout) as client:
                        response = await client.get(
                            f"{self._base_url}{path}",
                            params=query,
                            headers={"User-Agent": "Dota2DraftMonitor/0.1"},
                        )
                else:
                    response = await self._http_client.get(
                        f"{self._base_url}{path}",
                        params=query,
                        timeout=self._timeout,
                        headers={"User-Agent": "Dota2DraftMonitor/0.1"},
                    )
            except httpx.TransportError as exc:
                if attempt >= self._max_retries:
                    raise OpenDotaTemporaryError("Could not reach OpenDota.") from exc
                await asyncio.sleep(_retry_delay(self._retry_backoff_seconds, attempt))
                continue

            if response.status_code == 429 or response.status_code == 408 or response.status_code >= 500:
                if attempt >= self._max_retries:
                    if response.status_code == 429:
                        raise OpenDotaRateLimitedError(_retry_after_seconds(response))
                    raise OpenDotaTemporaryError(
                        f"OpenDota returned HTTP {response.status_code}."
                    )
                await asyncio.sleep(
                    _retry_delay(
                        self._retry_backoff_seconds,
                        attempt,
                        _retry_after_seconds(response),
                    )
                )
                continue
            if not 200 <= response.status_code < 300:
                raise OpenDotaHTTPError(response.status_code)

            try:
                return response.json()
            except ValueError as exc:
                raise OpenDotaInvalidResponseError(
                    "OpenDota returned invalid JSON."
                ) from exc

        raise OpenDotaTemporaryError("OpenDota request retry limit reached.")


def _normalize_pro_match(source: _ProMatchResponse) -> MatchSnapshot:
    game = ProviderMap(
        external_game_id=str(source.match_id),
        game_number=None,
        started_at=_as_datetime(source.start_time),
        duration_seconds=source.duration,
        radiant_team=ProviderTeam(
            external_team_id=_as_external_id(source.radiant_team_id),
            name=source.radiant_name,
        ),
        dire_team=ProviderTeam(
            external_team_id=_as_external_id(source.dire_team_id),
            name=source.dire_name,
        ),
        status=_completed_status(source.duration, source.radiant_win),
        radiant_won=_verified_radiant_win(
            source.radiant_win,
            source.radiant_score,
            source.dire_score,
            source.match_id,
        ),
        draft=None,
        radiant_score=source.radiant_score,
        dire_score=source.dire_score,
    )
    return MatchSnapshot(
        provider_match_id=str(source.match_id),
        provider_series_id=_as_external_id(source.series_id),
        league_name=source.league_name,
        league_id=_as_external_id(source.leagueid),
        series_type=source.series_type,
        radiant_team=game.radiant_team,
        dire_team=game.dire_team,
        map=game,
    )


def _normalize_live_match(source: _LiveMatchResponse) -> MatchSnapshot:
    picks: list[ProviderDraftPick] = []
    seen_orders: set[int] = set()
    seen_heroes: set[str] = set()
    rejected_players = 0
    for index, player in enumerate(source.players or []):
        try:
            live_player = _LivePlayerResponse.model_validate(player)
        except ValidationError:
            rejected_players += 1
            continue
        if live_player.hero_id == 0:
            continue
        side = {0: "radiant", 1: "dire"}.get(live_player.team)
        if side is None:
            rejected_players += 1
            continue
        pick_order = live_player.team * 5 + live_player.team_slot
        external_hero_id = str(live_player.hero_id)
        if pick_order in seen_orders or external_hero_id in seen_heroes:
            rejected_players += 1
            continue
        seen_orders.add(pick_order)
        seen_heroes.add(external_hero_id)
        picks.append(
            ProviderDraftPick(
                external_hero_id=external_hero_id,
                side=side,
                pick_order=pick_order,
            )
        )
    if rejected_players:
        logger.warning(
            "event=live_draft_players_rejected match_id=%s count=%d",
            source.match_id,
            rejected_players,
        )
    radiant_count = sum(pick.side == "radiant" for pick in picks)
    dire_count = sum(pick.side == "dire" for pick in picks)
    draft = (
        ProviderDraft(
            picks=tuple(sorted(picks, key=lambda pick: pick.pick_order)),
            pick_order_is_chronological=False,
        )
        if picks
        else None
    )
    game = ProviderMap(
        external_game_id=source.match_id,
        game_number=None,
        started_at=_as_datetime(source.activate_time),
        duration_seconds=None,
        radiant_team=ProviderTeam(
            external_team_id=str(source.team_id_radiant),
            name=source.team_name_radiant,
        ),
        dire_team=ProviderTeam(
            external_team_id=str(source.team_id_dire),
            name=source.team_name_dire,
        ),
        status="live",
        radiant_won=None,
        draft=draft,
    )
    return MatchSnapshot(
        provider_match_id=source.match_id,
        provider_series_id=_as_external_id(source.series_id),
        league_id=_as_external_id(source.league_id),
        series_type=source.series_type,
        radiant_team=game.radiant_team,
        dire_team=game.dire_team,
        map=game,
    )


def _hero_image_url(canonical_name: str) -> str | None:
    prefix = "npc_dota_hero_"
    if not canonical_name.startswith(prefix):
        return None
    image_name = canonical_name.removeprefix(prefix)
    if not image_name or any(
        character not in "abcdefghijklmnopqrstuvwxyz0123456789_"
        for character in image_name
    ):
        return None
    return (
        "https://cdn.cloudflare.steamstatic.com/apps/dota2/images/"
        f"dota_react/heroes/{image_name}.png"
    )


def _normalize_match(source: _MatchResponse) -> MatchSnapshot:
    radiant_team = ProviderTeam(
        external_team_id=_as_external_id(
            source.radiant_team_id
            if source.radiant_team_id is not None
            else source.radiant_team.team_id if source.radiant_team else None
        ),
        name=source.radiant_name
        or (source.radiant_team.name if source.radiant_team else None),
    )
    dire_team = ProviderTeam(
        external_team_id=_as_external_id(
            source.dire_team_id
            if source.dire_team_id is not None
            else source.dire_team.team_id if source.dire_team else None
        ),
        name=source.dire_name or (source.dire_team.name if source.dire_team else None),
    )
    league_name = source.league_name
    if league_name is None and source.league:
        value = source.league.get("name")
        league_name = value if isinstance(value, str) else None

    game = ProviderMap(
        external_game_id=str(source.match_id),
        game_number=None,
        started_at=_as_datetime(source.start_time),
        duration_seconds=source.duration,
        radiant_team=radiant_team,
        dire_team=dire_team,
        status=_completed_status(source.duration, source.radiant_win),
        radiant_won=_verified_radiant_win(
            source.radiant_win,
            source.radiant_score,
            source.dire_score,
            source.match_id,
        ),
        draft=_normalize_draft(source.picks_bans),
        radiant_score=source.radiant_score,
        dire_score=source.dire_score,
    )
    return MatchSnapshot(
        provider_match_id=str(source.match_id),
        provider_series_id=_as_external_id(source.series_id),
        league_name=league_name,
        league_id=_as_external_id(source.leagueid),
        series_type=source.series_type,
        radiant_team=radiant_team,
        dire_team=dire_team,
        map=game,
    )


def _normalize_draft(
    source_actions: list[dict[str, Any]] | None,
) -> ProviderDraft | None:
    if source_actions is None:
        return None

    picks: list[ProviderDraftPick] = []
    for index, action in enumerate(source_actions):
        try:
            action_data = _PickBanResponse.model_validate(action)
        except ValidationError:
            logger.warning("Ignoring malformed OpenDota pick/ban at response index %d.", index)
            continue
        if not action_data.is_pick:
            continue
        side = {0: "radiant", 1: "dire"}.get(action_data.team)
        if side is None:
            logger.warning("Ignoring OpenDota pick with unrecognized team value %d.", action_data.team)
            continue
        picks.append(
            ProviderDraftPick(
                external_hero_id=str(action_data.hero_id),
                side=side,
                pick_order=action_data.order + 1,
            )
        )

    return ProviderDraft(
        picks=tuple(sorted(picks, key=lambda pick: pick.pick_order))
    )


def _completed_status(duration: int | None, radiant_win: bool | None) -> str | None:
    if duration is not None and duration > 0 and radiant_win is not None:
        return "completed"
    return None


def _verified_radiant_win(
    radiant_win: bool | None,
    radiant_score: int | None,
    dire_score: int | None,
    match_id: int,
) -> bool | None:
    if radiant_win is None:
        return None
    if radiant_score is not None and dire_score is not None:
        scores_contradict = (
            radiant_win and radiant_score < dire_score
        ) or (not radiant_win and dire_score < radiant_score)
        if scores_contradict:
            logger.warning(
                "event=match_result_conflict match_id=%s radiant_win=%s "
                "radiant_score=%d dire_score=%d",
                match_id,
                radiant_win,
                radiant_score,
                dire_score,
            )
            return None
    return radiant_win


def _as_external_id(value: int | None) -> str | None:
    if value is None or value <= 0:
        return None
    return str(value)


def _as_datetime(timestamp: int | None) -> datetime | None:
    if timestamp is None or timestamp <= 0:
        return None
    try:
        return datetime.fromtimestamp(timestamp, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        logger.warning("Ignoring invalid OpenDota Unix timestamp.")
        return None


def _parse_match_id(provider_match_id: str) -> int:
    try:
        match_id = int(provider_match_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("OpenDota match ID must be a positive integer string.") from exc
    if match_id <= 0:
        raise ValueError("OpenDota match ID must be a positive integer string.")
    return match_id


def _retry_after_seconds(response: httpx.Response) -> float | None:
    value = response.headers.get("Retry-After")
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            from email.utils import parsedate_to_datetime

            retry_at = parsedate_to_datetime(value)
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=timezone.utc)
            return max(0.0, (retry_at - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None


def _retry_delay(
    backoff_seconds: float,
    attempt: int,
    retry_after: float | None = None,
) -> float:
    backoff = min(backoff_seconds * (2**attempt), 10.0)
    return min(max(backoff, retry_after or 0.0), 30.0)
