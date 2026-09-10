"""Reuse model fits only when every estimator input is identical."""

from collections import OrderedDict
from copy import deepcopy
from hashlib import sha256
from typing import Protocol

import numpy as np
import polars as pl

from .contrast_feature_table import ContrastFeatureSelection
from .contrast_screening import ContrastBalanceRejection
from .doubly_robust_estimation import DoublyRobustContrast


class ContrastEstimator(Protocol):
    def __call__(
        self,
        frame: pl.DataFrame,
        treatment: int,
        comparator: int,
        /,
        *,
        features: np.ndarray | None = None,
    ) -> DoublyRobustContrast | ContrastBalanceRejection: ...


class BranchContrastCache:
    def __init__(
        self,
        estimator: ContrastEstimator,
        capacity: int = 4096,
    ) -> None:
        if capacity < 1:
            raise ValueError("Contrast cache capacity must be at least 1")
        self.capacity = capacity
        self._estimator = estimator.__call__
        self.reused_fits = 0
        self.calculated_fits = 0
        self.rejected_at_balance = 0
        self._results: OrderedDict[
            tuple[int, int, bytes], DoublyRobustContrast | ContrastBalanceRejection
        ] = OrderedDict()

    def estimate_contrast(
        self,
        frame: pl.DataFrame,
        treatment: int,
        comparator: int,
        *,
        feature_selection: ContrastFeatureSelection | None = None,
    ) -> DoublyRobustContrast | ContrastBalanceRejection:
        key = treatment, comparator, sha256(frame.serialize(format="binary")).digest()
        if key in self._results:
            result = self._results.pop(key)
            self.reused_fits += 1
        else:
            result = self._estimator(
                frame,
                treatment,
                comparator,
                features=feature_selection.to_numpy()
                if feature_selection is not None
                else None,
            )
            self.calculated_fits += 1
            self.rejected_at_balance += isinstance(result, ContrastBalanceRejection)
        self._results[key] = result
        if len(self._results) > self.capacity:
            self._results.popitem(last=False)
        return deepcopy(result)
