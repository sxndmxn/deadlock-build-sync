"""Measure complete inventory support in a separate match partition."""

from __future__ import annotations

import math
from functools import lru_cache
from typing import TYPE_CHECKING

import numpy as np

from .records import mask_indices

if TYPE_CHECKING:
    from pathlib import Path

    from .records import Catalog, CombinationConfig, Query


def bitset(values: np.ndarray) -> int:
    return int.from_bytes(np.packbits(values, bitorder="little").tobytes(), "little")


def wilson_interval(wins: int, count: int) -> tuple[float | None, float | None]:
    if count == 0:
        return None, None
    z = 1.959963984540054
    rate = wins / count
    denominator = 1 + z * z / count
    center = (rate + z * z / (2 * count)) / denominator
    radius = (
        z
        * math.sqrt(rate * (1 - rate) / count + z * z / (4 * count * count))
        / denominator
    )
    return max(0, center - radius), min(1, center + radius)


@lru_cache(maxsize=6)
def load_ownership(path: Path) -> tuple[tuple[int, ...], int, tuple[int, ...], int]:
    with np.load(path) as values:
        matrix = values["matrix"]
        matches = values["matches"]
        if len(np.unique(matches)) != len(matches):
            raise ValueError("Ownership evidence contains duplicate hero matches")
        columns = tuple(bitset(matrix[:, index]) for index in range(matrix.shape[1]))
        won = bitset(values["won"])
        relative = tuple(
            bitset(values["relative_state"] == state) for state in range(3)
        )
        return columns, won, relative, len(matches)


class OwnershipEvidence:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def load(
        self, hero: int, checkpoint: int
    ) -> tuple[tuple[int, ...], int, tuple[int, ...], int]:
        return load_ownership(self.directory / f"{hero}-{checkpoint}.npz")

    def counts(
        self, hero: int, checkpoint: int, owned: int, relative_state: int | None = None
    ) -> dict[str, int | float | None]:
        columns, won, relative, total = self.load(hero, checkpoint)
        eligible = (
            (1 << total) - 1 if relative_state is None else relative[relative_state]
        )
        owners = eligible
        for item in mask_indices(owned):
            owners &= columns[item]
        count = owners.bit_count()
        wins = (owners & won).bit_count()
        baseline_count = eligible.bit_count()
        baseline_wins = (eligible & won).bit_count()
        lower, upper = wilson_interval(wins, count)
        return {
            "available": baseline_count > 0,
            "owners": count if baseline_count else None,
            "wins": wins if baseline_count else None,
            "win_rate": wins / count if count else None,
            "lower_95": lower,
            "upper_95": upper,
            "hero_matches": baseline_count,
            "hero_win_rate": baseline_wins / baseline_count if baseline_count else None,
        }


class JointSupport:
    def __init__(
        self,
        evidence: OwnershipEvidence,
        catalog: Catalog,
        query: Query,
        checkpoint: int,
        config: CombinationConfig,
    ) -> None:
        columns, _, relative, _ = evidence.load(query.hero, checkpoint)
        eligible = relative[query.relative_state]
        self.exact = tuple(column & eligible for column in columns)
        expanded = list(self.exact)
        for item, owners in enumerate(self.exact):
            for ancestor in mask_indices(catalog.ancestors[item]):
                expanded[ancestor] |= owners
        self.expanded = tuple(expanded)
        self.eligible = eligible
        self.config = config
        self.initial = query.owned
        self.cache: dict[tuple[int, bool], int] = {}

    def count(self, owned: int, *, expanded: bool) -> int:
        new_items = owned & ~self.initial
        key = new_items, expanded
        if key in self.cache:
            return self.cache[key]
        columns = self.expanded if expanded else self.exact
        owners = self.eligible
        for item in mask_indices(new_items):
            owners &= columns[item]
        count = owners.bit_count()
        if len(self.cache) >= 8192:
            self.cache.clear()
        self.cache[key] = count
        return count

    def feasible(self, owned: int) -> bool:
        return self.count(owned, expanded=True) >= self.config.minimum_owners

    def complete(self, owned: int) -> bool:
        return (
            owned & ~self.initial
        ).bit_count() >= self.config.minimum_items and self.count(
            owned, expanded=False
        ) >= self.config.minimum_owners
