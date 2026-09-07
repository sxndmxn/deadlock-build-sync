"""Measure observational outcomes without using them to reject supported cores."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import numpy as np
from scipy.stats import binomtest, norm

from deadlock_build_sync.build_support import outcome_limitations as rejection_reasons

from .discovery_ownership import joint_lift, ownership

if TYPE_CHECKING:
    from .discovery_data import HeroData

from .discovery_types import Adjusted, CoreEvaluation

__all__ = ["evaluate_core", "rejection_reasons", "standardized", "wilson_lower"]


def wilson_lower(wins: int, count: int, z: float = 1.96) -> float:
    if count == 0:
        return 0.0
    rate = wins / count
    return (
        rate
        + z * z / (2 * count)
        - z * math.sqrt(rate * (1 - rate) / count + z * z / (4 * count * count))
    ) / (1 + z * z / count)


def standardized(core: np.ndarray, won: np.ndarray, strata: np.ndarray) -> Adjusted:
    cells = 2 * strata + core.astype(int)
    size = 2 * (int(strata.max()) + 1) if len(strata) else 0
    counts = np.bincount(cells, minlength=size).reshape(-1, 2)
    wins = np.bincount(cells, weights=won, minlength=size).reshape(-1, 2)
    shared = (counts >= 10).all(axis=1)
    common_counts, common_wins = counts[shared], wins[shared]
    overlap = int(common_counts[:, 1].sum())
    result: Adjusted = {
        "core_overlap": overlap,
        "overlap_share": overlap / max(1, int(core.sum())),
        "strata": int(shared.sum()),
        "difference": None,
        "lower_95": None,
        "p_greater": 1.0,
    }
    if overlap < 100:
        return result
    weights = common_counts[:, 1] / overlap
    adjusted = weights @ (common_wins / common_counts)
    smoothed = (common_wins + 0.5) / (common_counts + 1)
    variance = float(
        (weights[:, None] ** 2 * smoothed * (1 - smoothed) / common_counts).sum()
    )
    difference, standard_error = float(adjusted[1] - adjusted[0]), math.sqrt(variance)
    result.update({
        "difference": difference,
        "standard_error": standard_error,
        "lower_95": difference - 1.96 * standard_error,
        "core_rate": float(adjusted[1]),
        "noncore_rate": float(adjusted[0]),
        "p_greater": float(norm.sf(difference / max(standard_error, 1e-15))),
    })
    return result


def state_strata(data: HeroData, rows: np.ndarray) -> np.ndarray:
    bins = np.column_stack((
        data.wealth[rows] // 5000,
        np.digitize(data.lead[rows], [-0.1, -0.03, 0.03, 0.1]),
        data.badge[rows] // 20,
    ))
    return np.unique(bins, axis=0, return_inverse=True)[1]


def evaluate_core(data: HeroData, items: tuple[int, ...], fold: str) -> CoreEvaluation:
    rows = data.mask(fold)
    index = {item: column for column, item in enumerate(data.items)}
    columns = tuple(index[item] for item in items)
    matrix, won = data.matrix[rows], data.won[rows]
    owned = ownership(matrix, columns)
    count, wins = int(owned.sum()), int(won[owned].sum())
    observed = np.isfinite(data.wealth[rows]) & np.isfinite(data.lead[rows])
    adjusted = standardized(
        owned[observed],
        won[observed],
        state_strata(data, rows & np.isfinite(data.wealth) & np.isfinite(data.lead)),
    )
    adjusted["overlap_share"] = adjusted["core_overlap"] / max(1, count)
    return {
        "fold": fold,
        "rows": len(won),
        "owners": count,
        "wins": wins,
        "win_rate": wins / count if count else None,
        "hero_win_rate": float(won.mean()) if len(won) else None,
        "coverage": count / max(1, len(won)),
        "joint_lift": joint_lift(matrix, columns, count),
        "win_lower_95": wilson_lower(wins, count),
        "win_p_greater_half": float(
            binomtest(wins, count, 0.5, alternative="greater").pvalue
        )
        if count
        else 1.0,
        "adjusted": adjusted,
    }
