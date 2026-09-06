"""Descriptive four-group contrasts; no causal purchase-effect interpretation."""

from __future__ import annotations

import math

import numpy as np


def stratified_contrast(
    first: np.ndarray,
    second: np.ndarray,
    won: np.ndarray,
    strata: np.ndarray,
    minimum_cell: int = 5,
    minimum_joint: int = 50,
) -> dict:
    arms = first.astype(int) + 2 * second.astype(int)
    cell = strata * 4 + arms
    size = (int(strata.max()) + 1) * 4
    counts = np.bincount(cell, minlength=size).reshape(-1, 4)
    wins = np.bincount(cell, weights=won, minlength=size).reshape(-1, 4)
    totals, total_wins = counts.sum(axis=0), wins.sum(axis=0)
    raw = [
        {"n": int(n), "wins": int(w), "win_rate": float(w / n) if n else None}
        for n, w in zip(totals, total_wins, strict=True)
    ]
    overlap = (counts >= minimum_cell).all(axis=1)
    common_counts, common_wins = counts[overlap], wins[overlap]
    shared = common_counts.sum(axis=0)
    result = {
        "groups": dict(
            zip(("neither", "first_only", "second_only", "both"), raw, strict=True)
        ),
        "overlap_strata": int(overlap.sum()),
        "overlap_group_counts": shared.tolist(),
        "joint_overlap_share": float(shared[3] / totals[3]) if totals[3] else 0,
        "adjusted": None,
    }
    if shared[3] < minimum_joint:
        return result
    # Standardize all four rates to the SAME concurrent-combo distribution over
    # strata with all four groups represented. No outcomes determine the weights.
    weights = common_counts[:, 3] / shared[3]
    rates = common_wins / common_counts
    smoothed = (common_wins + 0.5) / (common_counts + 1)
    variances = (weights[:, None] ** 2 * smoothed * (1 - smoothed) / common_counts).sum(
        axis=0
    )
    adjusted = (weights[:, None] * rates).sum(axis=0)
    result["adjusted"] = {
        "rates": adjusted.tolist(),
        "interaction": summarize(adjusted, variances, [1, -1, -1, 1]),
        "both_minus_first_only": summarize(adjusted, variances, [0, -1, 0, 1]),
        "both_minus_second_only": summarize(adjusted, variances, [0, 0, -1, 1]),
    }
    return result


def summarize(
    rates: np.ndarray, variances: np.ndarray, coefficients: list[int]
) -> dict:
    weights = np.asarray(coefficients)
    delta = float(rates @ weights)
    se = float(np.sqrt(variances @ (weights**2)))
    return {
        "difference": delta,
        "standard_error": se,
        "approximate_95_interval": [delta - 1.96 * se, delta + 1.96 * se],
        "two_sided_p": math.erfc(abs(delta) / (max(se, 1e-15) * math.sqrt(2))),
    }


def bh_adjust(pvalues: list[float]) -> list[float]:
    if not pvalues:
        return []
    values = np.asarray(pvalues)
    order = np.argsort(values, kind="stable")
    adjusted = values[order] * len(values) / np.arange(1, len(values) + 1)
    adjusted = np.minimum.accumulate(adjusted[::-1])[::-1].clip(0, 1)
    result = np.empty_like(values)
    result[order] = adjusted
    return result.tolist()
