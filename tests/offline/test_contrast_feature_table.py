from __future__ import annotations

import numpy as np
import polars as pl
import pytest
from threadpoolctl import threadpool_limits

from deadlock_build_sync.offline.contrast_feature_table import ContrastFeatureTable
from deadlock_build_sync.offline.contrast_features import build_contrast_feature_matrix
from deadlock_build_sync.offline.doubly_robust_estimation import (
    estimate_cross_fitted_doubly_robust_contrast,
)
from tests.offline.production_evidence_fixtures import make_contrast_rows


@pytest.mark.parametrize("indices", [[], [0], [1, 2], [2, 0, 2], [0, 1, 2]])
@pytest.mark.parametrize("existing_context", [False, True])
def test_packed_selections_preserve_feature_bytes(
    indices: list[int], *, existing_context: bool
) -> None:
    frame = pl.DataFrame({
        "average_badge": ["71", "invalid", "115"],
        "enemy_heroes": [[4, 2, 4], None, []],
        "enemy_items": [[], [8000000001], [9, 10]],
        "owned_before": [[], [8], [8, 1]],
        "relative_wealth": [1.2, None, float("nan")],
    })
    if existing_context:
        frame = frame.with_columns(
            pl.lit(9).alias("context_enemy_heroes_2"),
            pl.lit("1.5").alias("context_custom"),
            pl.lit(-1).alias("context_relative_wealth"),
        )
    table = ContrastFeatureTable.from_frame(frame)
    expected = build_contrast_feature_matrix(frame[indices, :])
    actual = table.select(np.asarray(indices, dtype=np.intp))
    np.testing.assert_array_equal(actual, expected)
    assert actual.tobytes() == expected.tobytes()
    assert actual.flags.c_contiguous


@pytest.mark.parametrize(
    "frame",
    [
        pl.DataFrame({"average_badge": [80, 90]}),
        pl.DataFrame({"relative_wealth": [None], "enemy_items": [[]]}),
        pl.DataFrame({"enemy_items": [["item_b", "item_a"], []]}),
    ],
)
def test_packed_tables_support_missing_and_empty_context(frame: pl.DataFrame) -> None:
    table = ContrastFeatureTable.from_frame(frame)
    for indices in (np.arange(frame.height), np.empty(0, dtype=np.intp)):
        expected = build_contrast_feature_matrix(frame[indices, :])
        actual = table.select(indices)
        np.testing.assert_array_equal(actual, expected)
        assert actual.tobytes() == expected.tobytes()


def test_shared_feature_predictions_match_direct_contrast() -> None:
    frame = pl.DataFrame(make_contrast_rows(positive=True))
    frame = frame.with_columns(
        pl.Series(
            "enemy_items",
            [[10, 20] if index % 3 else [30] for index in range(frame.height)],
        )
    )
    features = ContrastFeatureTable.from_frame(frame).select(np.arange(frame.height))
    with threadpool_limits(limits=1):
        expected = estimate_cross_fitted_doubly_robust_contrast(frame, 10, 20)
        actual = estimate_cross_fitted_doubly_robust_contrast(
            frame, 10, 20, features=features
        )
    assert actual == expected
