"""Reuse model fits only when every estimator input is identical."""

from collections import OrderedDict
from collections.abc import Callable
from copy import deepcopy
from hashlib import sha256

import polars as pl

from .doubly_robust_estimation import DoublyRobustContrast


class BranchContrastCache:
    def __init__(
        self,
        estimator: Callable[[pl.DataFrame, int, int], DoublyRobustContrast],
        capacity: int = 4096,
    ) -> None:
        if capacity < 1:
            raise ValueError("Contrast cache capacity must be at least 1")
        self.capacity = capacity
        self._estimator = estimator
        self.reused_fits = 0
        self.calculated_fits = 0
        self._results: OrderedDict[tuple[int, int, bytes], DoublyRobustContrast] = (
            OrderedDict()
        )

    def estimate_contrast(
        self, frame: pl.DataFrame, treatment: int, comparator: int
    ) -> DoublyRobustContrast:
        key = treatment, comparator, sha256(frame.serialize(format="binary")).digest()
        if key in self._results:
            result = self._results.pop(key)
            self.reused_fits += 1
        else:
            result = self._estimator(frame, treatment, comparator)
            self.calculated_fits += 1
        self._results[key] = result
        if len(self._results) > self.capacity:
            self._results.popitem(last=False)
        return deepcopy(result)
