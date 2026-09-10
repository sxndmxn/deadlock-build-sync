"""Count complete cores and assign new cores to frozen groups."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from deadlock_build_sync.guide_generator import BEAM_SETTINGS
from deadlock_build_sync.purchase_windows import wilson_score_interval

if TYPE_CHECKING:
    from deadlock_build_sync.mechanics import ItemGraph

    from .discovery_data import HeroDiscoveryData


def wealth_state(value: float) -> int | None:
    if not np.isfinite(value) or value <= 0:
        return None
    return 0 if value < 0.9 else 2 if value > 1.1 else 1


def assign_core_group(
    core: frozenset[int], groups: dict[str, tuple[frozenset[int], ...]]
) -> str | None:
    existing = [group for group, members in groups.items() if core in members]
    if existing:
        return existing[0] if len(existing) == 1 else None
    eligible = [
        group
        for group, members in groups.items()
        if all(
            len(core & member) >= 2
            and len(core & member) / len(core | member)
            >= BEAM_SETTINGS["minimum_group_similarity"]
            for member in members
        )
    ]
    return eligible[0] if len(eligible) == 1 else None


class BeamOwnership:
    def __init__(self, values: HeroDiscoveryData, graph: ItemGraph, state: int) -> None:
        self.exact: dict[int, int] = {}
        self.expanded: dict[int, int] = {}
        self.eligible = 0
        for index, owned in enumerate(values.inventories):
            if (
                values.folds[index] != "discovery"
                or wealth_state(values.relative_wealth[index]) != state
            ):
                continue
            bit = 1 << index
            self.eligible |= bit
            for item in owned:
                self.exact[item] = self.exact.get(item, 0) | bit
                for component in (item, *graph.transitive_components(item)):
                    self.expanded[component] = self.expanded.get(component, 0) | bit
        self.cache: dict[tuple[tuple[int, ...], bool], int] = {}

    def count(self, core: tuple[int, ...], *, expanded: bool = False) -> int:
        key = tuple(sorted(core)), expanded
        if key not in self.cache:
            columns = self.expanded if expanded else self.exact
            owners = self.eligible
            for item in core:
                owners &= columns.get(item, 0)
            self.cache[key] = owners.bit_count()
        return self.cache[key]


def core_state_statistics(
    values: HeroDiscoveryData, core: tuple[int, ...], state: int
) -> dict[str, object]:
    result: dict[str, object] = {}
    required = set(core)
    ownership = np.asarray(
        [required.issubset(owned) for owned in values.inventories], dtype=bool
    )
    matched = np.asarray(
        [wealth_state(value) == state for value in values.relative_wealth], dtype=bool
    )
    for fold in ("discovery", "selection", "validation"):
        eligible = values.fold_mask(fold) & matched
        owners = eligible & ownership
        count, wins = int(owners.sum()), int(values.won[owners].sum())
        total = int(eligible.sum())
        lower, upper = wilson_score_interval(wins, count)
        result[fold] = {
            "owners": count,
            "wins": wins,
            "win_rate": wins / count if count else None,
            "lower_95": lower if count else None,
            "upper_95": upper if count else None,
            "hero_matches": total,
            "hero_win_rate": float(values.won[eligible].mean()) if total else None,
            "ownership_before_seconds": values.ownership_before_seconds,
        }
    return result
