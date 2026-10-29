from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime
from typing import Literal, Protocol, Sequence


@dataclass(frozen=True)
class ProviderTeam:
    external_team_id: str | None
    name: str | None


@dataclass(frozen=True)
class ProviderHero:
    external_hero_id: str
    name: str
    image_url: str | None = None


@dataclass(frozen=True)
class BatruHero:
    external_hero_id: str
    canonical_name: str
    display_name: str
    short_name: str


@dataclass(frozen=True)
class ProviderDraftPick:
    external_hero_id: str
    side: Literal["radiant", "dire"]
    pick_order: int
    position: Literal["unknown"] = "unknown"


@dataclass(frozen=True)
class ProviderDraft:
    picks: Sequence[ProviderDraftPick]
    pick_order_is_chronological: bool = True


@dataclass(frozen=True)
class ProviderMap:
    external_game_id: str
    game_number: int | None
    started_at: datetime | None
    duration_seconds: int | None
    radiant_team: ProviderTeam
    dire_team: ProviderTeam
    status: Literal["scheduled", "live", "completed", "cancelled"] | None
    radiant_won: bool | None
    draft: ProviderDraft | None
    radiant_score: int | None = None
    dire_score: int | None = None


@dataclass(frozen=True)
class MatchSnapshot:
    provider_match_id: str
    provider_series_id: str | None
    league_name: str | None = None
    league_id: str | None = None
    series_type: int | None = None
    radiant_team: ProviderTeam = ProviderTeam(None, None)
    dire_team: ProviderTeam = ProviderTeam(None, None)
    map: ProviderMap | None = None


@dataclass(frozen=True)
class ProviderMatchDetails:
    match: MatchSnapshot
    map: ProviderMap


@dataclass(frozen=True)
class Draft:
    radiant_heroes: Sequence[str]
    dire_heroes: Sequence[str]


@dataclass(frozen=True)
class DraftPrediction:
    radiant_probability: Decimal
    dire_probability: Decimal


class MatchProvider(Protocol):
    async def get_current_matches(
        self, *, less_than_match_id: int | None = None
    ) -> Sequence[MatchSnapshot]:
        """Return the provider's latest professional-match history."""
        ...

    async def get_live_matches(self) -> Sequence[MatchSnapshot]:
        """Return currently active professional games when supported."""
        ...

    async def get_match_details(self, provider_match_id: str) -> ProviderMatchDetails:
        """Return normalized details for one provider match identifier."""
        ...

    async def get_map_and_draft(self, provider_match_id: str) -> ProviderMap:
        """Return normalized map and draft data, when present at the provider."""
        ...

    async def get_match_status(self, provider_match_id: str) -> str | None:
        """Return a known normalized status, or None when the provider cannot determine it."""
        ...

    async def get_hero_directory(self) -> Sequence[ProviderHero]:
        """Return the provider's hero ID/name directory for draft-pick resolution."""
        ...


class BatruClient(Protocol):
    async def predict_draft(self, draft: Draft) -> DraftPrediction:
        """Return normalized draft probabilities from Batru."""
        ...

    async def get_hero_directory(self) -> Sequence[BatruHero]:
        """Return Batru's Dota 2 hero identities and request shortNames."""
        ...
