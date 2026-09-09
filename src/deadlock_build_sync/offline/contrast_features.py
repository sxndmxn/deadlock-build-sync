"""Construct the fixed state features and observed context indicators."""

from __future__ import annotations

import numpy as np
import polars as pl

from .effect_estimation_limits import STATE_FEATURES

CONTRAST_COLUMNS = frozenset({
    *STATE_FEATURES,
    "match_id",
    "player_slot",
    "item_id",
    "won",
    "fold",
    "enemy_heroes",
    "enemy_items",
    "owned_before",
    "relative_wealth",
})


def select_contrast_row(row: dict[str, object]) -> dict[str, object]:
    return {
        name: value
        for name, value in row.items()
        if name in CONTRAST_COLUMNS or name.startswith("context_")
    }


def build_feature_matrix(frame: pl.DataFrame) -> np.ndarray:
    names = set(frame.columns)
    extra = sorted(name for name in names if name.startswith("context_"))
    columns = [
        pl.col(name).cast(pl.Float64, strict=False).fill_nan(None)
        if name in names
        else pl.repeat(None, frame.height, dtype=pl.Float64).alias(name)
        for name in (*STATE_FEATURES, *extra)
    ]
    return frame.select(columns).to_numpy(order="c")


def build_contrast_feature_matrix(frame: pl.DataFrame) -> np.ndarray:
    base = build_feature_matrix(frame)
    extra = sorted(name for name in frame.columns if name.startswith("context_"))
    context = {
        name: base[:, len(STATE_FEATURES) + index] for index, name in enumerate(extra)
    }
    context.update(_context_indicators(frame))
    if _has_relative_wealth(frame):
        context["context_relative_wealth"] = (
            frame["relative_wealth"]
            .cast(pl.Float64, strict=False)
            .fill_nan(None)
            .to_numpy()
        )
    return np.column_stack([
        base[:, : len(STATE_FEATURES)],
        *(context[name] for name in sorted(context)),
    ])


def _has_relative_wealth(frame: pl.DataFrame) -> bool:
    return (
        "relative_wealth" in frame.columns
        and frame["relative_wealth"].null_count() < frame.height
    )


def _context_indicators(frame: pl.DataFrame) -> dict[str, np.ndarray]:
    columns = {}
    for feature in ("enemy_heroes", "enemy_items", "owned_before"):
        if feature not in frame.columns:
            continue
        groups = frame[feature].to_list()
        items = sorted({item for group in groups for item in (group or [])})
        positions = {item: index for index, item in enumerate(items)}
        indicators = np.zeros((len(groups), len(items)), dtype=np.int64)
        for row_index, group in enumerate(groups):
            for item in group or []:
                indicators[row_index, positions[item]] = 1
        columns.update(
            (f"context_{feature}_{item}", indicators[:, index])
            for index, item in enumerate(items)
        )
    return columns
