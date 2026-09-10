from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from deadlock_build_sync.offline.contrast_observations import ContrastObservations


@pytest.mark.parametrize("folds", [2, 5, 10])
def test_match_groups_preserve_original_fold_assignment_and_row_order(
    folds: int,
) -> None:
    matches = np.array([9, 4, 9, 1, 2, 4])
    frame = pl.DataFrame({
        "match_id": matches,
        "treatment": np.arange(len(matches)) % 2,
        "won": np.arange(len(matches)) % 3 == 0,
    })
    features = np.arange(18).reshape(6, 3)
    observations = ContrastObservations.from_frame(frame, features)
    assignments = {
        match: index % min(folds, len(set(matches)))
        for index, match in enumerate(sorted(set(matches)))
    }
    np.testing.assert_array_equal(
        observations.match_folds(folds), [assignments[match] for match in matches]
    )
    selected = np.array([True, False, True, True, False, False])
    subset = observations.select(selected)
    np.testing.assert_array_equal(subset.features, features[selected])
    np.testing.assert_array_equal(subset.match_ids, matches[selected])
    np.testing.assert_array_equal(subset.outcome, frame["won"].to_numpy()[selected])


@pytest.mark.parametrize("matches", [[1, 1], [1, float("nan")]])
def test_match_groups_reject_incomplete_identifiers(matches: list[float]) -> None:
    values = np.array(matches)
    observations = ContrastObservations(
        np.ones((2, 1)), np.array([0, 1]), np.ones(2), values
    )
    with pytest.raises(ValueError, match="match"):
        observations.match_folds(5)


@pytest.mark.parametrize("folds", [0, -1])
def test_match_groups_reject_invalid_fold_counts(folds: int) -> None:
    observations = ContrastObservations(
        np.ones((2, 1)), np.array([0, 1]), np.ones(2), np.array([1, 2])
    )
    with pytest.raises(ValueError, match="at least one fold"):
        observations.match_folds(folds)
