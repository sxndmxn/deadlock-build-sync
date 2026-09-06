"""Whole-match temporal partitions and inventories strictly before 20 minutes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .discovery_types import LandmarkRow

if TYPE_CHECKING:
    import duckdb

from collections import Counter, defaultdict
from dataclasses import dataclass

import numpy as np

from deadlock_build_sync.mechanics import ItemGraph

from .late_game import reconstruct_final_inventory


@dataclass
class HeroData:
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

    def mask(self, fold: str) -> np.ndarray:
        return self.folds == fold


def prepare_partitions(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("""
        CREATE OR REPLACE TEMP TABLE discovery_partitions AS
        WITH matches AS (
            SELECT p.match_id, min(p.start_time) AS started
            FROM player_matches p JOIN match_folds f USING(match_id)
            WHERE f.fold='train' GROUP BY p.match_id
        )
        SELECT match_id,
            CASE WHEN row_number() OVER(ORDER BY started,match_id)
                      <= floor(count(*) OVER()*0.75)
                 THEN 'discovery' ELSE 'selection' END AS partition
        FROM matches
        UNION ALL
        SELECT match_id, 'validation' FROM match_folds WHERE fold='validation'
    """)


def landmark_rows(con: duckdb.DuckDBPyConnection, hero: int) -> list[LandmarkRow]:
    return con.execute(
        """
        WITH actors AS (
            SELECT p.*, d.partition, 1199 AS checkpoint
            FROM player_matches p JOIN discovery_partitions d USING(match_id)
            WHERE p.hero_id=? AND p.duration_s>=1200
        ), personal AS (
            SELECT a.*, s.net_worth AS wealth, s.stat_time AS observed
            FROM actors a ASOF LEFT JOIN player_snapshots s
            ON a.match_id=s.match_id AND a.player_slot=s.player_slot
               AND a.checkpoint>=s.stat_time
        ), own_team AS (
            SELECT p.*, t.team_net_worth AS own_wealth,
                   t.observed_players AS own_count, t.stat_time AS own_observed
            FROM personal p ASOF LEFT JOIN team_snapshots t
            ON p.match_id=t.match_id AND p.team_id=t.team_id
               AND p.checkpoint>=t.stat_time
        ), both_teams AS (
            SELECT p.*, t.team_net_worth AS enemy_wealth,
                   t.observed_players AS enemy_count, t.stat_time AS enemy_observed
            FROM own_team p ASOF LEFT JOIN team_snapshots t
            ON p.match_id=t.match_id AND (1-p.team_id)=t.team_id
               AND p.checkpoint>=t.stat_time
        )
        SELECT p.match_id, p.player_slot, p.partition, p.won, p.wealth,
               (p.own_wealth-p.enemy_wealth)/(p.own_wealth+p.enemy_wealth),
               p.average_badge, p.wealth*12/(p.own_wealth+p.enemy_wealth), c.hero_ids
        FROM both_teams p JOIN compositions c
          ON p.match_id=c.match_id AND (1-p.team_id)=c.team_id
        WHERE p.wealth>0 AND p.own_wealth+p.enemy_wealth>0
          AND p.own_count=6 AND p.enemy_count=6 AND len(c.hero_ids)=6
          AND 1200-p.observed BETWEEN 1 AND 300
          AND 1200-p.own_observed BETWEEN 1 AND 300
          AND 1200-p.enemy_observed BETWEEN 1 AND 300
        ORDER BY p.start_time, p.match_id, p.player_slot
    """,
        [hero],
    ).fetchall()


def purchase_histories(
    con: duckdb.DuckDBPyConnection, hero: int
) -> dict[tuple[int, int], list[tuple[int, int, int]]]:
    rows = con.execute(
        """
        SELECT p.match_id,p.player_slot,p.item_id,p.buy_time,p.sold_time
        FROM purchases p JOIN discovery_partitions d USING(match_id)
        WHERE p.hero_id=? AND p.buy_time<1200
        ORDER BY p.match_id,p.player_slot,p.buy_time,p.event_order
    """,
        [hero],
    ).fetchall()
    histories: dict[tuple[int, int], list[tuple[int, int, int]]] = defaultdict(list)
    for match, slot, item, bought, sold in rows:
        histories[int(match), int(slot)].append((
            int(item),
            int(bought),
            int(sold) if sold and sold < 1200 else 0,
        ))
    return dict(histories)


def from_rows(
    hero: int,
    rows: list[LandmarkRow],
    histories: dict[tuple[int, int], list[tuple[int, int, int]]],
    graph: ItemGraph,
) -> HeroData:
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
    minimum = max(100, int(np.ceil(sum(row[2] == "discovery" for row in rows) * 0.01)))
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
    return _hero_arrays(hero, items, rows, times, actors, inventories)


def _hero_arrays(
    hero: int,
    items: tuple[int, ...],
    rows: list[LandmarkRow],
    times: np.ndarray,
    actors: tuple[tuple[int, int], ...],
    inventories: tuple[tuple[int, ...], ...],
) -> HeroData:
    return HeroData(
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
        np.asarray([row[8] for row in rows], dtype=np.int64).reshape(-1, 6),
        actors,
        inventories,
    )


def load_data(con: duckdb.DuckDBPyConnection, hero: int, graph: ItemGraph) -> HeroData:
    count = con.execute(
        "SELECT count(*) FROM player_matches WHERE hero_id=?", [hero]
    ).fetchone()
    if count is None or count[0] == 0:
        raise ValueError(f"Hero {hero} has no source data; run refresh-evidence again")
    return from_rows(
        hero, landmark_rows(con, hero), purchase_histories(con, hero), graph
    )
