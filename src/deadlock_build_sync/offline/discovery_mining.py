"""Outcome-blind, supported extensions of Eclat seed combinations."""

from __future__ import annotations

import math
from itertools import combinations

import numpy as np

from .discovery_config import (
    EXTENSION_RETENTION,
    MAXIMUM_COST,
    MINIMUM,
    PER_SIZE,
)
from .discovery_patterns import eclat
from .discovery_types import Candidate, Catalog, Mining, PatternCounts


def valid_items(items: tuple[int, ...], catalog: Catalog) -> bool:
    if not 3 <= len(items) <= 6 or len(set(items)) != len(items):
        return False
    if any(str(item) not in catalog for item in items):
        return False
    assets = [catalog[str(item)] for item in items]
    return (
        min(asset["cost"] for asset in assets) >= 1600
        and sum(asset["cost"] for asset in assets) <= MAXIMUM_COST
        and not any(set(items) & set(asset["ancestors"]) for asset in assets)
    )


def parent_for(
    columns: tuple[int, ...], count: int, previous: PatternCounts
) -> tuple[int, ...] | None:
    if len(columns) == 3:
        return ()
    eligible = [
        parent
        for parent in combinations(columns, len(columns) - 1)
        if parent in previous and count / previous[parent] >= EXTENSION_RETENTION
    ]
    return min(eligible) if eligible else None


def qualify(
    raw: PatternCounts,
    previous: PatternCounts,
    item_ids: tuple[int, ...],
    marginal: np.ndarray,
    rows: int,
    catalog: Catalog,
) -> tuple[list[Candidate], PatternCounts]:
    candidates: list[Candidate] = []
    qualified: PatternCounts = {}
    for columns, count in raw.items():
        items = tuple(item_ids[column] for column in columns)
        if not valid_items(items, catalog):
            continue
        parent = parent_for(columns, count, previous)
        lift = count / rows / float(marginal[list(columns)].prod())
        if parent is None or lift < 1.1:
            continue
        qualified[columns] = count
        candidates.append({
            "items": list(items),
            "names": [catalog[str(item)]["name"] for item in items],
            "cost": sum(catalog[str(item)]["cost"] for item in items),
            "discovery_support": count,
            "discovery_lift": lift,
            "score": count / rows * math.log(lift),
            "parent": [item_ids[column] for column in parent],
            "parent_retention": count / previous[parent] if parent else None,
        })
    ranked = sorted(candidates, key=lambda row: (-row["score"], row["items"]))
    return ranked[:PER_SIZE], qualified


def mine(
    matrix: np.ndarray, times: np.ndarray, item_ids: tuple[int, ...], catalog: Catalog
) -> Mining:
    if not np.array_equal(matrix, times >= 0) or (times >= 1200).any():
        raise ValueError("Inventory/latest acquisition mismatch or future event")
    if not len(matrix):
        return {"candidates": [], "sizes": {}}
    previous: PatternCounts = {}
    selected: list[Candidate] = []
    diagnostics: dict[str, dict[str, int]] = {}
    marginal = matrix.mean(axis=0)
    for length in range(3, 7):
        raw = eclat(matrix, minimum=MINIMUM, length=length)
        rows, previous = qualify(
            raw, previous, item_ids, marginal, len(matrix), catalog
        )
        selected.extend(rows)
        diagnostics[str(length)] = {
            "frequent": len(raw),
            "qualified": len(previous),
            "retained": len(rows),
        }
    return {"candidates": selected, "sizes": diagnostics}
