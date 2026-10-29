from uuid import uuid4

from app.integrations.batru_hero_mapper import BatruHeroMapper
from app.models import BatruHeroMapping, DraftPick, Hero


def test_full_draft_maps_exact_short_names_to_the_correct_sides():
    radiant_names = ("axe", "bane", "chen", "drow_ranger", "earthshaker")
    dire_names = ("abaddon", "alchemist", "ancient_apparition", "antimage", "arc_warden")
    picks = []

    for index, short_name in enumerate(radiant_names + dire_names, start=1):
        hero_id = uuid4()
        hero = Hero(
            id=hero_id,
            provider="opendota",
            external_hero_id=str(index),
            name=f"Hero {index}",
        )
        hero.batru_mapping = BatruHeroMapping(
            external_hero_id=str(index),
            short_name=short_name,
        )
        picks.append(
            DraftPick(
                hero_id=hero_id,
                hero=hero,
                side="radiant" if index <= 5 else "dire",
                pick_order=index,
            )
        )

    draft = BatruHeroMapper.to_batru_draft(list(reversed(picks)))

    assert tuple(draft.radiant_heroes) == radiant_names
    assert tuple(draft.dire_heroes) == dire_names
    assert len(set(draft.radiant_heroes)) == len(set(draft.dire_heroes)) == 5
