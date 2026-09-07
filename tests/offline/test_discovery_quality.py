"""Exact mining and admission regressions moved into the main suite."""

from itertools import combinations
from typing import TYPE_CHECKING

import numpy as np
import pytest

from deadlock_build_sync.offline.discovery_patterns import eclat, prefixspan
from deadlock_build_sync.offline.discovery_quality import (
    rejection_reasons,
    standardized,
    wilson_lower,
)

if TYPE_CHECKING:
    from deadlock_build_sync.offline.discovery_types import CoreEvaluation


def test_eclat_matches_exhaustive_triples_and_unique_transaction_support() -> None:
    matrix = np.random.default_rng(42).random((80, 8)) < 0.6
    expected = {
        core: int(matrix[:, core].all(axis=1).sum())
        for core in combinations(range(8), 3)
        if matrix[:, core].all(axis=1).sum() >= 10
    }
    assert eclat(matrix, minimum=10) == expected


def test_prefixspan_matches_strict_time_order_and_does_not_order_ties() -> None:
    times = np.array([[10, 10, 20], [10, 15, 20], [30, 20, 10], [1, -1, 2]])
    assert prefixspan(times, minimum=1) == {(0, 1, 2): 1, (2, 1, 0): 1}
    assert prefixspan(times, minimum=2) == {}


def test_prefixspan_counts_same_sequence_once_and_agrees_with_brute_force() -> None:
    rng = np.random.default_rng(17)
    times = rng.integers(-1, 5, size=(40, 5))
    patterns = prefixspan(times, minimum=1)
    for pattern, count in patterns.items():
        selected = times[:, pattern]
        expected = int(
            ((selected[:, 0] >= 0) & (np.diff(selected, axis=1) > 0).all(axis=1)).sum()
        )
        assert count == expected


def test_state_adjustment_removes_mixture_selection_and_sparse_overlap_abstains() -> (
    None
):
    # The core occurs mostly in a high-win stratum, but has no within-stratum gain.
    core, strata, won = [], [], []
    for stratum, counts in enumerate(((900, 100), (100, 900))):
        for arm, count in enumerate(counts):
            core.extend([arm == 1] * count)
            strata.extend([stratum] * count)
            won.extend(np.arange(count) < (0.2 if stratum == 0 else 0.8) * count)
    result = standardized(np.asarray(core), np.asarray(won), np.asarray(strata))
    assert result["difference"] == pytest.approx(0, abs=1e-12)
    assert result["lower_95"] is not None
    assert result["lower_95"] < 0
    sparse = standardized(
        np.ones(100, dtype=bool), np.ones(100), np.zeros(100, dtype=int)
    )
    assert sparse["difference"] is None
    assert sparse["p_greater"] == pytest.approx(1)


def test_high_raw_win_rate_cannot_bypass_quality_or_multiple_testing() -> None:
    result: CoreEvaluation = {
        "owners": 500,
        "wins": 350,
        "win_rate": 0.7,
        "joint_lift": 2,
        "win_lower_95": wilson_lower(350, 500),
        "win_p_greater_half": 0.001,
        "adjusted": {
            "core_overlap": 450,
            "overlap_share": 0.9,
            "difference": 0.02,
            "standard_error": 0.005,
            "lower_95": 0.01,
            "p_greater": 0.02,
        },
    }
    assert not rejection_reasons(result)
    assert rejection_reasons(result, 50) == [
        "win evidence fails family correction",
        "adjusted evidence fails family correction",
    ]
    result["adjusted"]["lower_95"] = -0.01
    assert "adjusted lower bound does not exceed zero" in rejection_reasons(result)
