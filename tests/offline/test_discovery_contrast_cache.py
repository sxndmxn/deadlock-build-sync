from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl
import pytest
from threadpoolctl import threadpool_limits

from deadlock_build_sync.offline.discovery_contrast_cache import BranchContrastCache
from deadlock_build_sync.offline.doubly_robust_estimation import (
    estimate_cross_fitted_doubly_robust_contrast,
)
from tests.offline.production_evidence_fixtures import make_contrast_rows

if TYPE_CHECKING:
    from deadlock_build_sync.offline.doubly_robust_estimation import (
        DoublyRobustContrast,
    )


def test_cached_contrasts_match_direct_fits_and_isolate_returned_records() -> None:
    frame = pl.DataFrame(make_contrast_rows(positive=True))
    cache = BranchContrastCache(estimate_cross_fitted_doubly_robust_contrast)
    with threadpool_limits(limits=1):
        expected = estimate_cross_fitted_doubly_robust_contrast(frame, 10, 20)
        first = cache.estimate_contrast(frame, 10, 20)
        assert first == expected
        first.fold_diagnostics["train"]["estimate"] = 99
        assert cache.estimate_contrast(frame.clone(), 10, 20) == expected
        changed = frame.with_columns((1 - pl.col("won")).alias("won"))
        assert cache.estimate_contrast(changed, 10, 20) == (
            estimate_cross_fitted_doubly_robust_contrast(changed, 10, 20)
        )
        assert cache.estimate_contrast(frame, 20, 10) == (
            estimate_cross_fitted_doubly_robust_contrast(frame, 20, 10)
        )
    assert cache.calculated_fits == 3
    assert cache.reused_fits == 1


def test_contrast_cache_bounds_memory_and_retries_failed_fits() -> None:
    frame = pl.DataFrame(make_contrast_rows(positive=True))
    with threadpool_limits(limits=1):
        contrast = estimate_cross_fitted_doubly_robust_contrast(frame, 10, 20)
    calls: list[int] = []

    def estimate(
        data: pl.DataFrame, _treatment: int, _comparator: int
    ) -> DoublyRobustContrast:
        identifier = int(data["id"][0])
        calls.append(identifier)
        if identifier == 0:
            raise ValueError("Invalid comparison frame")
        return contrast

    cache = BranchContrastCache(estimate, capacity=2)
    for identifier in (1, 2, 1, 3, 2):
        cache.estimate_contrast(pl.DataFrame({"id": [identifier]}), 10, 20)
    assert calls == [1, 2, 3, 2]
    assert cache.calculated_fits == 4
    assert cache.reused_fits == 1
    for _attempt in range(2):
        with pytest.raises(ValueError, match="Invalid comparison frame"):
            cache.estimate_contrast(pl.DataFrame({"id": [0]}), 10, 20)
    assert calls[-2:] == [0, 0]
    with pytest.raises(ValueError, match="at least 1"):
        BranchContrastCache(estimate, capacity=0)
