"""Extend supported Eclat itemsets without using match outcomes."""

from __future__ import annotations

import math
from itertools import combinations

import numpy as np

from .discovery_config import (
    MAXIMUM_CANDIDATES_PER_SIZE,
    MAXIMUM_CORE_COST,
    MINIMUM_CORE_OWNERS,
    MINIMUM_EXTENSION_RETENTION,
)
from .discovery_patterns import mine_eclat_itemsets
from .discovery_types import (
    CoreDiscoveryCandidate,
    CoreMiningResult,
    DiscoveryItemCatalog,
    ItemsetSupportCounts,
)


def are_valid_core_items(items: tuple[int, ...], catalog: DiscoveryItemCatalog) -> bool:
    if not 3 <= len(items) <= 6 or len(set(items)) != len(items):
        return False
    if any(str(item) not in catalog for item in items):
        return False
    assets = [catalog[str(item)] for item in items]
    return (
        min(asset["cost"] for asset in assets) >= 1600
        and sum(asset["cost"] for asset in assets) <= MAXIMUM_CORE_COST
        and not any(set(items) & set(asset["ancestors"]) for asset in assets)
    )


def select_supported_parent(
    columns: tuple[int, ...], count: int, previous: ItemsetSupportCounts
) -> tuple[int, ...] | None:
    if len(columns) == 3:
        return ()
    eligible = [
        parent
        for parent in combinations(columns, len(columns) - 1)
        if parent in previous
        and count / previous[parent] >= MINIMUM_EXTENSION_RETENTION
    ]
    return min(eligible) if eligible else None


def qualify_itemsets(
    raw: ItemsetSupportCounts,
    previous: ItemsetSupportCounts,
    item_ids: tuple[int, ...],
    marginal: np.ndarray,
    rows: int,
    catalog: DiscoveryItemCatalog,
) -> tuple[list[CoreDiscoveryCandidate], ItemsetSupportCounts]:
    candidates: list[CoreDiscoveryCandidate] = []
    qualified: ItemsetSupportCounts = {}
    for columns, count in raw.items():
        items = tuple(item_ids[column] for column in columns)
        if not are_valid_core_items(items, catalog):
            continue
        parent = select_supported_parent(columns, count, previous)
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
    return ranked[:MAXIMUM_CANDIDATES_PER_SIZE], qualified


def mine_core_candidates(
    matrix: np.ndarray,
    times: np.ndarray,
    item_ids: tuple[int, ...],
    catalog: DiscoveryItemCatalog,
) -> CoreMiningResult:
    if not np.array_equal(matrix, times >= 0) or (times >= 1200).any():
        raise ValueError(
            "Inventory does not match acquisition times, or a purchase occurs after the checkpoint"
        )
    if not len(matrix):
        return {"candidates": [], "sizes": {}}
    previous: ItemsetSupportCounts = {}
    selected: list[CoreDiscoveryCandidate] = []
    diagnostics: dict[str, dict[str, int]] = {}
    marginal = matrix.mean(axis=0)
    for length in range(3, 7):
        raw = mine_eclat_itemsets(matrix, minimum=MINIMUM_CORE_OWNERS, length=length)
        rows, previous = qualify_itemsets(
            raw, previous, item_ids, marginal, len(matrix), catalog
        )
        selected.extend(rows)
        diagnostics[str(length)] = {
            "frequent": len(raw),
            "qualified": len(previous),
            "retained": len(rows),
        }
    return {"candidates": selected, "sizes": diagnostics}
