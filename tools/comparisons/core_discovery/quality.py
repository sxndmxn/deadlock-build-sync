"""Comparison adapter for the shared production implementation."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from deadlock_build_sync.offline.discovery_ownership import ownership
from deadlock_build_sync.offline.discovery_quality import (
    evaluate_core,
    rejection_reasons,
    standardized,
    state_strata,
    wilson_lower,
)

__all__ = [
    "context_cells",
    "evaluate_core",
    "rejection_reasons",
    "standardized",
    "state_strata",
    "wilson_lower",
]

if TYPE_CHECKING:
    from deadlock_build_sync.offline.discovery_data import HeroData


def context_cells(
    data: HeroData, items: tuple[int, ...]
) -> dict[str, dict[str, int | float]]:
    rows = data.mask("validation")
    index = {item: column for column, item in enumerate(data.items)}
    core = ownership(data.matrix[rows], tuple(index[item] for item in items))
    relative, enemies, won = (
        data.relative_wealth[rows],
        data.enemies[rows],
        data.won[rows],
    )
    conditions = {
        "behind": relative < 0.9,
        "even": (relative >= 0.9) & (relative <= 1.1),
        "ahead": relative > 1.1,
    }
    conditions.update({
        f"enemy:{hero}": (enemies == hero).any(axis=1) for hero in np.unique(enemies)
    })
    result = {}
    for name, condition in conditions.items():
        selected = core & condition
        count = int(selected.sum())
        if count >= 50:
            result[name] = {
                "owners": count,
                "wins": int(won[selected].sum()),
                "win_rate": float(won[selected].mean()),
                "all_players_in_context_win_rate": float(won[condition].mean()),
            }
    return result
