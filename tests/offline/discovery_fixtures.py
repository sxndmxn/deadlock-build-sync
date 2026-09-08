"""Shared graph, match data, and frozen outputs for discovery tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from deadlock_build_sync.mechanics import ItemGraph, ItemNode
from deadlock_build_sync.offline.discovery_data import HeroData

if TYPE_CHECKING:
    import duckdb

    from deadlock_build_sync.offline.discovery_types import (
        Catalog,
        FrozenGuide,
        Nomination,
        Tactics,
    )


def graph_fixture(count: int = 12, *, active: bool = False) -> ItemGraph:
    return ItemGraph({
        item: ItemNode(
            item,
            f"item{item}",
            f"Item {item}",
            1600,
            "weapon",
            2,
            (),
            active=active,
            unique=True,
            max_count=1,
        )
        for item in range(count)
    })


def catalog_fixture(count: int) -> Catalog:
    return {
        str(item): {"cost": 1600, "name": f"Item {item}", "ancestors": []}
        for item in range(count)
    }


def planted_data(seed: int = 17, per_fold: int = 1200) -> HeroData:
    rng = np.random.default_rng(seed)
    size = per_fold * 3
    group = np.tile(np.arange(per_fold) % 3, 3)
    matrix = np.zeros((size, 13), dtype=bool)
    for identity in range(3):
        matrix[group == identity, identity * 4 : identity * 4 + 4] = True
    matrix[:, 12] = rng.random(size) < 0.65
    times = np.where(matrix, 100 + 55 * np.arange(13)[None, :], -1).astype(np.int32)
    won = rng.random(size) < np.asarray([0.75, 0.65, 0.25])[group]
    return HeroData(
        6,
        tuple(range(13)),
        matrix,
        times,
        np.arange(size),
        np.repeat(["discovery", "selection", "validation"], per_fold),
        won,
        np.full(size, 15000.0),
        np.zeros(size),
        np.full(size, 90),
        np.ones(size),
        np.zeros((size, 6), dtype=int),
    )


def frozen_guide(
    _con: duckdb.DuckDBPyConnection, _data: HeroData, row: Nomination, _graph: ItemGraph
) -> FrozenGuide:
    return {
        "ready": True,
        "path": row["path"]["order"],
        "pool": {"1": [], "2": [], "3": [], "4": []},
        "bounds": {},
        "purchase_timing": {"items": []},
        "pool_statistics": {},
    }


def supported_tactics(*_args: object) -> Tactics:
    return {
        "supported_focus": True,
        "focuses": [],
        "item_evidence": {},
        "reason": None,
        "limitation": "observational",
    }
