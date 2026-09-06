"""Exact mining, sequence semantics, latent fits, and evidence admission checks."""

from __future__ import annotations

from itertools import combinations

import numpy as np
import pytest
from threadpoolctl import threadpool_limits

from tools.comparisons.core_discovery.candidates import discover, valid_core
from tools.comparisons.core_discovery.latent import (
    bernoulli_fit,
    bernoulli_log_prob,
    leiden,
)
from tools.comparisons.core_discovery.patterns import eclat, prefixspan
from tools.comparisons.core_discovery.quality import (
    evaluate_core,
    rejection_reasons,
    standardized,
    wilson_lower,
)
from tools.comparisons.core_discovery.synthetic import planted_data


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


def test_core_contract_excludes_component_pairs_and_unaffordable_triples() -> None:
    catalog = {str(item): {"cost": 1600, "ancestors": []} for item in range(4)}
    catalog["1"]["ancestors"] = [0]
    catalog["3"]["cost"] = 12800
    assert not valid_core((0, 1, 2), catalog)
    assert not valid_core((0, 2, 3), catalog)
    assert not valid_core((1, 1, 2), catalog)
    assert not valid_core((0, 2), catalog)


def test_discovery_rejects_future_acquisitions_before_running_a_model() -> None:
    with pytest.raises(ValueError, match="pre-landmark"):
        discover(
            "eclat",
            np.ones((1, 3), dtype=bool),
            np.array([[100, 200, 1200]]),
            (1, 2, 3),
            {},
            42,
        )


def test_bernoulli_likelihood_and_em_recover_binary_profiles() -> None:
    theta = np.array([[0.8, 0.2], [0.1, 0.7]])
    actual = bernoulli_log_prob(np.array([[1.0, 0.0]]), theta, np.array([0.4, 0.6]))
    np.testing.assert_allclose(np.exp(actual), [[0.4 * 0.8 * 0.8, 0.6 * 0.1 * 0.3]])
    data = np.vstack((np.tile([1, 1, 0, 0], (200, 1)), np.tile([0, 0, 1, 1], (200, 1))))
    with threadpool_limits(limits=1):
        profiles, diagnostic = bernoulli_fit(data, 42, components=2)
    assert np.max(profiles[:, 0]) > 0.9
    assert np.min(profiles[:, 0]) < 0.1
    assert np.all(np.diff(diagnostic["penalized_log_likelihood"]) >= -1e-7)


def test_leiden_recovers_disconnected_item_communities() -> None:
    data = np.zeros((600, 6), dtype=bool)
    data[:300, :3] = True
    data[300:, 3:] = True
    with threadpool_limits(limits=1):
        cores, diagnostic = leiden(data, 42)
    assert cores == {(0, 1, 2), (3, 4, 5)}
    assert diagnostic["edges"] == 6


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
    assert result["lower_95"] < 0
    sparse = standardized(
        np.ones(100, dtype=bool), np.ones(100), np.zeros(100, dtype=int)
    )
    assert sparse["difference"] is None
    assert sparse["p_greater"] == pytest.approx(1)


def test_high_raw_win_rate_cannot_bypass_quality_or_multiple_testing() -> None:
    result = {
        "owners": 500,
        "win_rate": 0.7,
        "joint_lift": 2,
        "win_lower_95": wilson_lower(350, 500),
        "win_p_greater_half": 0.001,
        "adjusted": {
            "core_overlap": 450,
            "overlap_share": 0.9,
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


def test_selection_statistics_do_not_read_other_folds_outcomes() -> None:
    data, _ = planted_data(per_fold=1200)
    original = evaluate_core(data, (100, 101, 102), "selection")
    assert original["adjusted"]["difference"] is not None
    data.won[~data.mask("selection")] = ~data.won[~data.mask("selection")]
    assert evaluate_core(data, (100, 101, 102), "selection") == original
