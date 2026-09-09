from __future__ import annotations

import math

import numpy as np
import polars as pl
import pytest

from deadlock_build_sync.offline.balance_diagnostics import (
    calculate_maximum_weighted_standardized_difference,
)
from deadlock_build_sync.offline.contrast_features import (
    build_contrast_feature_matrix,
    build_feature_matrix,
)
from deadlock_build_sync.offline.doubly_robust_estimation import (
    _calculate_cluster_interval,
)
from deadlock_build_sync.offline.effect_estimation_limits import STATE_FEATURES


def _scalar_standardized_difference(
    features: np.ndarray, treatment: np.ndarray, propensity: np.ndarray
) -> float:
    maximum = 0.0
    weights = np.where(treatment == 1, 1 / propensity, 1 / (1 - propensity))
    for column in features.T:
        treated = np.isfinite(column) & (treatment == 1)
        control = np.isfinite(column) & (treatment == 0)
        if not treated.any() or not control.any():
            continue
        treated_mean = np.average(column[treated], weights=weights[treated])
        control_mean = np.average(column[control], weights=weights[control])
        pooled = math.sqrt(
            (
                np.average(
                    (column[treated] - treated_mean) ** 2, weights=weights[treated]
                )
                + np.average(
                    (column[control] - control_mean) ** 2, weights=weights[control]
                )
            )
            / 2
        )
        if pooled > 0:
            maximum = max(maximum, abs(treated_mean - control_mean) / pooled)
        elif treated_mean != control_mean:
            return float("inf")
    return maximum


@pytest.mark.parametrize("rows", [4, 31, 257])
@pytest.mark.parametrize("missing", [False, True])
def test_balance_reductions_match_scalar_diagnostics(
    rows: int, *, missing: bool
) -> None:
    generator = np.random.default_rng(731)
    features = generator.normal(size=(rows, 23))
    treatment = np.arange(rows) % 2
    propensity = generator.uniform(0.05, 0.95, rows)
    features[:, 0] = 1
    if missing:
        features[::3, 2] = np.nan
        features[:, 5] = np.nan
        features[treatment == 1, 7] = np.inf
    actual = calculate_maximum_weighted_standardized_difference(
        features, treatment, propensity
    )
    assert actual == _scalar_standardized_difference(features, treatment, propensity)


def test_balance_handles_absent_groups_and_constant_differences() -> None:
    features = np.array([[0.0, np.nan], [0.0, np.nan], [1.0, 1.0], [1.0, 1.0]])
    propensity = np.full(4, 0.5)
    for treatment in (np.zeros(4), np.ones(4), np.array([0, 0, 1, 1])):
        assert calculate_maximum_weighted_standardized_difference(
            features, treatment, propensity
        ) == _scalar_standardized_difference(features, treatment, propensity)
    assert (
        calculate_maximum_weighted_standardized_difference(
            np.full((4, 2), np.nan), np.array([0, 0, 1, 1]), propensity
        )
        == 0
    )


@pytest.mark.parametrize("matches", [[5, 3, 1, 2], [5, 1, 5, 1], [1, 1, 1, 1]])
def test_cluster_intervals_keep_match_order_and_repeated_match_means(
    matches: list[int],
) -> None:
    match_ids = np.array(matches)
    influence = np.array([1.01, -2.3, 0.007, 9.13])
    clusters = np.array([
        influence[match_ids == match].mean() for match in np.unique(match_ids)
    ])
    radius = (
        1.96 * float(np.std(clusters, ddof=1) / math.sqrt(len(clusters)))
        if len(clusters) > 1
        else 0
    )
    estimate = float(influence.mean())
    assert _calculate_cluster_interval(influence, match_ids) == (
        estimate - radius,
        estimate + radius,
    )


def test_feature_matrix_preserves_order_casts_and_missing_values() -> None:
    frame = pl.DataFrame({
        "phase": [1.0, float("nan"), None],
        "average_badge": ["71", "invalid", "115"],
        "context_z": [9, 8, 7],
        "context_a": [1, 2, 3],
    })
    expected = np.full((3, len(STATE_FEATURES) + 2), np.nan)
    expected[:, 0] = [71, np.nan, 115]
    expected[:, 1] = [1, np.nan, np.nan]
    expected[:, -2:] = [[1, 9], [2, 8], [3, 7]]
    np.testing.assert_array_equal(build_feature_matrix(frame), expected)
    assert build_feature_matrix(frame.clear()).shape == (0, expected.shape[1])


def add_reference_context_features(frame: pl.DataFrame) -> pl.DataFrame:
    columns = []
    for feature in ("enemy_heroes", "enemy_items", "owned_before"):
        if feature in frame.columns:
            groups = frame[feature].to_list()
            columns.extend(
                pl.Series(
                    f"context_{feature}_{item}",
                    [int(item in (group or [])) for group in groups],
                )
                for item in sorted({item for group in groups for item in (group or [])})
            )
    if (
        "relative_wealth" in frame.columns
        and frame["relative_wealth"].null_count() < frame.height
    ):
        columns.append(frame["relative_wealth"].alias("context_relative_wealth"))
    return frame.with_columns(columns)


def test_context_indicators_keep_sorted_items_and_duplicate_membership() -> None:
    frame = pl.DataFrame({
        "enemy_heroes": [[4, 2, 4], None, []],
        "owned_before": [[], [8], [8, 1]],
        "relative_wealth": [1.2, None, 0.8],
    })
    cases = [
        frame,
        frame.with_columns(pl.lit(9).alias("context_enemy_heroes_2")),
        frame.with_columns(pl.lit("1.5").alias("context_custom")),
        frame.clear(),
        pl.DataFrame({"relative_wealth": [None], "enemy_items": [[]]}),
    ]
    for candidate in cases:
        np.testing.assert_array_equal(
            build_contrast_feature_matrix(candidate),
            build_feature_matrix(add_reference_context_features(candidate)),
        )
