from collections.abc import Sequence

from app.integrations.interfaces import Draft as BatruDraft
from app.models import DraftPick


class UnmappedBatruHeroError(ValueError):
    def __init__(self, picks: Sequence[DraftPick]) -> None:
        details = [
            f"{pick.hero.name} (id={pick.hero_id}, "
            f"{pick.hero.provider}:{pick.hero.external_hero_id})"
            for pick in picks
        ]
        super().__init__(
            "No verified Batru shortName mapping for: " + ", ".join(details) + "."
        )
        self.hero_ids = tuple(str(pick.hero_id) for pick in picks)


class BatruHeroMapper:
    @staticmethod
    def to_batru_draft(picks: Sequence[DraftPick]) -> BatruDraft:
        radiant: list[str] = []
        dire: list[str] = []
        unmapped: list[DraftPick] = []

        for pick in sorted(picks, key=lambda item: item.pick_order):
            mapping = pick.hero.batru_mapping
            if (
                mapping is None
                or not mapping.short_name.strip()
                or mapping.external_hero_id != pick.hero.external_hero_id
            ):
                unmapped.append(pick)
                continue
            if pick.side == "radiant":
                radiant.append(mapping.short_name)
            elif pick.side == "dire":
                dire.append(mapping.short_name)
            else:
                raise ValueError(f"Unsupported draft side: {pick.side}")

        if unmapped:
            raise UnmappedBatruHeroError(unmapped)
        if len(set(radiant + dire)) != len(radiant) + len(dire):
            raise ValueError("Batru mappings contain duplicate shortNames.")
        return BatruDraft(radiant_heroes=tuple(radiant), dire_heroes=tuple(dire))
