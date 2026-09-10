"""Share numeric columns and packed context indicators between row selections."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import polars as pl

from .contrast_features import build_feature_matrix
from .effect_estimation_limits import STATE_FEATURES


@dataclass(frozen=True)
class ContrastFeatureTable:
    numeric: np.ndarray
    extra_names: tuple[str, ...]
    indicators: np.ndarray
    indicator_names: tuple[str, ...]
    relative_wealth: np.ndarray | None
    relative_observed: np.ndarray | None

    @classmethod
    def from_frame(cls, frame: pl.DataFrame) -> ContrastFeatureTable:
        indicators, names = _pack_context_indicators(frame)
        relative = frame.get_column("relative_wealth", default=None)
        return cls(
            build_feature_matrix(frame),
            tuple(
                sorted(name for name in frame.columns if name.startswith("context_"))
            ),
            indicators,
            names,
            relative.cast(pl.Float64, strict=False).fill_nan(None).to_numpy()
            if relative is not None
            else None,
            relative.is_not_null().to_numpy() if relative is not None else None,
        )

    def select(self, indices: np.ndarray) -> np.ndarray:
        selected = np.unpackbits(
            self.indicators[indices], axis=1, count=len(self.indicator_names)
        )
        active = np.flatnonzero(selected.any(axis=0))
        indicator_names = [self.indicator_names[index] for index in active]
        relative = (
            self.relative_observed is not None and self.relative_observed[indices].any()
        )
        names = sorted(
            set(self.extra_names)
            | set(indicator_names)
            | ({"context_relative_wealth"} if relative else set())
        )
        offsets = {
            name: len(STATE_FEATURES) + index for index, name in enumerate(names)
        }
        result = np.zeros((len(indices), len(STATE_FEATURES) + len(names)))
        result[:, : len(STATE_FEATURES)] = self.numeric[indices, : len(STATE_FEATURES)]
        for index, name in enumerate(self.extra_names):
            result[:, offsets[name]] = self.numeric[
                indices, len(STATE_FEATURES) + index
            ]
        result[:, [offsets[name] for name in indicator_names]] = selected[:, active]
        if relative and self.relative_wealth is not None:
            result[:, offsets["context_relative_wealth"]] = self.relative_wealth[
                indices
            ]
        return result


def _pack_context_indicators(
    frame: pl.DataFrame,
) -> tuple[np.ndarray, tuple[str, ...]]:
    rows, columns, names = [], [], []
    for feature in ("enemy_heroes", "enemy_items", "owned_before"):
        if feature not in frame.columns:
            continue
        groups = frame[feature].to_list()
        items = sorted({item for group in groups for item in (group or [])})
        positions = {item: len(names) + index for index, item in enumerate(items)}
        names.extend(f"context_{feature}_{item}" for item in items)
        for row, group in enumerate(groups):
            for item in group or []:
                rows.append(row)
                columns.append(positions[item])
    indicators = np.zeros((frame.height, len(names)), dtype=np.uint8)
    indicators[rows, columns] = 1
    return np.packbits(indicators, axis=1), tuple(names)


@dataclass(frozen=True)
class ContrastFeatureSelection:
    table: ContrastFeatureTable
    indices: np.ndarray

    def to_numpy(self) -> np.ndarray:
        return self.table.select(self.indices)
