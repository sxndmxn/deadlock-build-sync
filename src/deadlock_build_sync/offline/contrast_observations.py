"""Store model observations in aligned column arrays and integer match groups."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    import polars as pl


@dataclass(frozen=True)
class ContrastObservations:
    features: np.ndarray
    treatment: np.ndarray
    outcome: np.ndarray
    match_ids: np.ndarray

    @classmethod
    def from_frame(
        cls, frame: pl.DataFrame, features: np.ndarray
    ) -> ContrastObservations:
        return cls(
            features,
            frame["treatment"].cast(int).to_numpy(),
            frame["won"].cast(int).to_numpy(),
            frame["match_id"].cast(int).to_numpy(),
        )

    def select(self, selected: np.ndarray) -> ContrastObservations:
        return ContrastObservations(
            self.features[selected],
            self.treatment[selected],
            self.outcome[selected],
            self.match_ids[selected],
        )

    def match_folds(self, folds: int) -> np.ndarray:
        if folds < 1:
            raise ValueError("Cross-fitting requires at least one fold")
        matches, groups = np.unique(self.match_ids, return_inverse=True)
        if len(matches) < 2:
            raise ValueError("cross-fitting requires at least two match groups")
        if not np.isfinite(matches).all():
            raise ValueError("Cross-fitting requires finite match identifiers")
        return groups % min(folds, len(matches))
