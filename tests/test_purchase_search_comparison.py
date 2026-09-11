"""Check paired comparison direction and match-cluster resampling."""

from __future__ import annotations

import numpy as np

from tools.purchase_search.comparison import cluster_interval


def test_cluster_resampling_preserves_identical_method_results() -> None:
    result = cluster_interval(np.zeros(4), np.asarray([1, 1, 2, 3]))
    assert result == (0, 0, 0)


def test_cluster_resampling_uses_record_weights_and_repeats() -> None:
    values = np.asarray([1, 1, 0, -1])
    groups = np.asarray([1, 1, 2, 3])
    first = cluster_interval(values, groups)
    assert first == cluster_interval(values, groups)
    assert first[0] == 0.25
    assert first[1] <= first[0] <= first[2]
