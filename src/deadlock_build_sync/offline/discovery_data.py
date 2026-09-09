"""Whole-match temporal partitions and inventories strictly before 20 minutes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .discovery_types import HeroLandmarkRow
from .sql_resources import load_sql

if TYPE_CHECKING:
    import duckdb

from collections import Counter, defaultdict
from dataclasses import dataclass, replace

import numpy as np

from deadlock_build_sync.build_support import SUPPORT
from deadlock_build_sync.mechanics import ItemGraph

from .inventory_reconstruction import reconstruct_final_inventory


@dataclass
class HeroDiscoveryData:
    hero: int
    items: tuple[int, ...]
    matrix: np.ndarray
    times: np.ndarray
    matches: np.ndarray
    folds: np.ndarray
    won: np.ndarray
    wealth: np.ndarray
    lead: np.ndarray
    badge: np.ndarray
    relative_wealth: np.ndarray
    enemies: np.ndarray
    actors: tuple[tuple[int, int], ...] = ()
    inventories: tuple[tuple[int, ...], ...] = ()

    def fold_mask(self, fold: str) -> np.ndarray:
        return self.folds == fold


def prepare_discovery_partitions(connection: duckdb.DuckDBPyConnection) -> None:
    if connection.execute(
        load_sql("discovery/count_split_boundaries.sql")
    ).fetchone() == (1,):
        connection.execute(load_sql("discovery/create_fixed_partitions.sql"))
        return
    connection.execute(load_sql("discovery/create_ranked_partitions.sql"))


def load_landmark_rows(
    connection: duckdb.DuckDBPyConnection, hero: int
) -> list[HeroLandmarkRow]:
    return connection.execute(
        load_sql("discovery/select_landmark_rows.sql"),
        {"hero": hero},
    ).fetchall()


def load_purchase_histories(
    connection: duckdb.DuckDBPyConnection, hero: int
) -> dict[tuple[int, int], list[tuple[int, int, int]]]:
    rows = connection.execute(
        load_sql("discovery/select_purchase_histories.sql"),
        {"hero": hero},
    ).fetchall()
    histories: dict[tuple[int, int], list[tuple[int, int, int]]] = defaultdict(list)
    for match, slot, item, bought, sold in rows:
        histories[int(match), int(slot)].append((
            int(item),
            int(bought),
            int(sold) if sold and sold < 1200 else 0,
        ))
    return dict(histories)


def build_hero_discovery_data(
    hero: int,
    rows: list[HeroLandmarkRow],
    histories: dict[tuple[int, int], list[tuple[int, int, int]]],
    graph: ItemGraph,
) -> HeroDiscoveryData:
    actors = tuple((int(row[0]), int(row[1])) for row in rows)
    if len(set(actors)) != len(actors) or len({row[0] for row in actors}) != len(
        actors
    ):
        raise ValueError("Discovery contains duplicate hero appearances in a match")
    inventories = tuple(
        reconstruct_final_inventory(histories.get(actor, []), graph.components)
        for actor in actors
    )
    support: Counter[int] = Counter()
    for row, owned in zip(rows, inventories, strict=True):
        if row[2] == "discovery":
            support.update(set(owned))
    minimum = max(
        SUPPORT.core_owners,
        int(np.ceil(sum(row[2] == "discovery" for row in rows) * 0.01)),
    )
    items = tuple(
        sorted(
            item
            for item, count in support.items()
            if graph.require(item).cost >= 1600 and count >= minimum
        )
    )
    times = np.full((len(rows), len(items)), -1, dtype=np.int32)
    index = {item: column for column, item in enumerate(items)}
    for offset, (actor, owned) in enumerate(zip(actors, inventories, strict=True)):
        for item, bought, _ in histories.get(actor, []):
            if item in index and item in owned:
                times[offset, index[item]] = max(times[offset, index[item]], bought)
    return replace(
        _build_hero_arrays(hero, items, rows, times),
        actors=actors,
        inventories=inventories,
    )


def _build_hero_arrays(
    hero: int,
    items: tuple[int, ...],
    rows: list[HeroLandmarkRow],
    times: np.ndarray,
) -> HeroDiscoveryData:
    return HeroDiscoveryData(
        hero,
        items,
        times >= 0,
        times,
        np.asarray([row[0] for row in rows], dtype=np.int64),
        np.asarray([row[2] for row in rows], dtype="U12"),
        np.asarray([row[3] for row in rows], dtype=bool),
        np.asarray([row[4] for row in rows], dtype=float),
        np.asarray([row[5] for row in rows], dtype=float),
        np.asarray([row[6] for row in rows], dtype=int),
        np.asarray([row[7] for row in rows], dtype=float),
        np.asarray(
            [
                row[8] if row[8] is not None and len(row[8]) == 6 else [0] * 6
                for row in rows
            ],
            dtype=np.int64,
        ).reshape(-1, 6),
    )


def load_hero_discovery_data(
    connection: duckdb.DuckDBPyConnection,
    hero: int,
    graph: ItemGraph,
    minimum: int = 11,
    maximum: int = 116,
) -> HeroDiscoveryData:
    count = connection.execute(
        load_sql("discovery/count_hero_appearances.sql"), {"hero": hero}
    ).fetchone()
    if count is None or count[0] == 0:
        raise ValueError(f"Hero {hero} has no source data; run refresh-evidence again")
    return build_hero_discovery_data(
        hero,
        [
            row
            for row in load_landmark_rows(connection, hero)
            if minimum <= row[6] <= maximum
        ],
        load_purchase_histories(connection, hero),
        graph,
    )
