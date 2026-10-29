from collections.abc import Sequence
from uuid import UUID

from app.models import DraftPick


def is_draft_complete(picks: Sequence[DraftPick]) -> bool:
    if len(picks) != 10:
        return False

    hero_ids: set[UUID] = set()
    external_hero_ids: set[tuple[str, str]] = set()
    side_counts = {"radiant": 0, "dire": 0}
    for pick in picks:
        hero = pick.hero
        if (
            pick.side not in side_counts
            or pick.hero_id is None
            or hero is None
            or not hero.provider.strip()
            or not hero.external_hero_id.strip()
        ):
            return False
        external_id = (hero.provider, hero.external_hero_id)
        if pick.hero_id in hero_ids or external_id in external_hero_ids:
            return False
        hero_ids.add(pick.hero_id)
        external_hero_ids.add(external_id)
        side_counts[pick.side] += 1

    return (
        len(hero_ids) == 10
        and len(external_hero_ids) == 10
        and side_counts["radiant"] == 5
        and side_counts["dire"] == 5
    )
