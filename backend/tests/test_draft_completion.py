from uuid import uuid4

import pytest

from app.models import DraftPick, Hero
from app.services.draft_completion import is_draft_complete


def picks(count=10, *, radiant_count=5, hero_ids=None):
    hero_ids = hero_ids or [uuid4() for _ in range(count)]
    result = []
    for index in range(count):
        hero_id = hero_ids[index]
        hero = Hero(
            id=hero_id,
            provider="opendota",
            external_hero_id=str(index + 1),
            name=f"Hero {index + 1}",
        )
        result.append(
            DraftPick(
                hero_id=hero_id,
                hero=hero,
                side="radiant" if index < radiant_count else "dire",
                pick_order=index + 1,
            )
        )
    return result


def test_five_distinct_valid_heroes_per_side_are_complete():
    assert is_draft_complete(picks()) is True


def test_nine_valid_heroes_are_incomplete():
    assert is_draft_complete(picks(count=9, radiant_count=5)) is False


def test_four_dire_heroes_are_incomplete():
    assert is_draft_complete(picks(radiant_count=6)) is False


def test_duplicate_hero_does_not_count_as_an_additional_pick():
    duplicate_id = uuid4()
    draft_picks = picks(hero_ids=[duplicate_id] + [uuid4() for _ in range(9)])
    draft_picks[-1].hero_id = duplicate_id
    draft_picks[-1].hero.id = duplicate_id

    assert is_draft_complete(draft_picks) is False


def test_duplicate_canonical_external_identity_does_not_count_twice():
    draft_picks = picks()
    draft_picks[-1].hero.provider = draft_picks[0].hero.provider
    draft_picks[-1].hero.external_hero_id = draft_picks[0].hero.external_hero_id

    assert is_draft_complete(draft_picks) is False


def test_unknown_canonical_hero_id_is_not_valid_for_completion():
    draft_picks = picks()
    draft_picks[-1].hero.external_hero_id = ""

    assert is_draft_complete(draft_picks) is False


@pytest.mark.parametrize(
    "sides",
    [
        ["radiant"] * 5 + ["dire"] * 5,
        ["radiant"] * 4 + ["dire"] * 6,
        ["radiant"] * 6 + ["dire"] * 4,
    ],
)
def test_completion_requires_exactly_five_picks_per_side(sides):
    draft_picks = picks()
    for pick, side in zip(draft_picks, sides, strict=True):
        pick.side = side

    assert is_draft_complete(draft_picks) is (sides.count("radiant") == 5)
