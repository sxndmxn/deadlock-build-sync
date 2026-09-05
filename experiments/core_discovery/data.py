"""Freeze full-corpus 20-minute inventories without any existing build labels."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

import duckdb
import numpy as np

from experiments.qdfm.extract import HEROES, fingerprint
from experiments.qdfm.state import Catalog


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

    def mask(self, fold: str) -> np.ndarray:
        return self.folds == fold


def write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )


def load_hero(directory: Path, hero: int) -> HeroData:
    with np.load(directory / f"hero-{hero}.npz", allow_pickle=False) as arrays:
        return HeroData(
            hero,
            tuple(arrays["items"].tolist()),
            *(
                arrays[name]
                for name in (
                    "matrix",
                    "times",
                    "matches",
                    "folds",
                    "won",
                    "wealth",
                    "lead",
                    "badge",
                    "relative_wealth",
                    "enemies",
                )
            ),
        )


def save_hero(
    con: duckdb.DuckDBPyConnection, catalog: Catalog, hero: int, output: Path
) -> dict:
    columns = con.execute(
        "SELECT * FROM frozen WHERE hero_id=? ORDER BY start_time, match_id, player_slot",
        [hero],
    ).fetchnumpy()
    folds = columns["partition"]
    discovery = folds == "discovery"
    support = {}
    for owned in columns["current_items"][discovery]:
        for item in owned:
            support[int(item)] = support.get(int(item), 0) + 1
    minimum = max(100, int(np.ceil(discovery.sum() * 0.01)))
    items = tuple(
        sorted(
            item
            for item, count in support.items()
            if item in catalog.costs
            and catalog.costs[item] >= 1600
            and count >= minimum
        )
    )
    index = {item: column for column, item in enumerate(items)}
    times = np.full((len(folds), len(items)), -1, dtype=np.int32)
    for row, (owned, acquired) in enumerate(
        zip(columns["current_items"], columns["acquired_times"], strict=True)
    ):
        for item, time in zip(owned, acquired, strict=True):
            if item in index:
                times[row, index[item]] = time
    np.savez_compressed(
        output / f"hero-{hero}.npz",
        items=np.asarray(items, dtype=np.int64),
        matrix=times >= 0,
        times=times,
        matches=columns["match_id"].astype(np.int64),
        folds=folds.astype("U12"),
        won=columns["won"].astype(bool),
        wealth=columns["wealth"].astype(float),
        lead=columns["team_lead_share"].astype(float),
        badge=columns["average_badge"].astype(int),
        relative_wealth=columns["relative_wealth"].astype(float),
        enemies=np.stack(columns["enemy_heroes"]).astype(np.int64),
    )
    return {
        "items": len(items),
        "minimum_item_support": minimum,
        "rows": {
            fold: int((folds == fold).sum())
            for fold in ("discovery", "selection", "validation")
        },
    }


def prepare(replay: Path, output: Path) -> None:
    previous = json.loads((replay / "data-manifest.json").read_text())
    if fingerprint(replay / "landmarks.parquet") != previous["landmarks_sha256"]:
        raise ValueError("Frozen inventory replay changed")
    source = Path(previous["source"])
    catalog = Catalog(source)
    output.mkdir(parents=True, exist_ok=False)
    con = duckdb.connect(str(source / "raw/analysis.duckdb"), read_only=True)
    con.execute("SET threads=2")
    con.execute("SET memory_limit='2GB'")
    con.execute("""
        CREATE TEMP TABLE training_partition AS
        WITH timestamps AS (
            SELECT p.match_id, min(start_time) AS started
            FROM player_matches p JOIN match_folds f USING(match_id)
            WHERE f.fold='train' GROUP BY p.match_id
        )
        SELECT match_id, started,
          CASE WHEN row_number() OVER(ORDER BY started,match_id)<=floor(count(*) OVER()*0.75)
               THEN 'discovery' ELSE 'selection' END AS partition
        FROM timestamps
    """)
    con.execute(
        """
        CREATE TEMP TABLE observations AS
        SELECT l.*, p.start_time, coalesce(t.partition,'validation') AS partition,
               c.hero_ids AS enemy_heroes,
               l.wealth::DOUBLE*12/(l.own_team_wealth+l.enemy_team_wealth) AS relative_wealth
        FROM read_parquet(?) l JOIN player_matches p USING(match_id,player_slot)
        LEFT JOIN training_partition t USING(match_id)
        JOIN compositions c ON l.match_id=c.match_id AND (1-l.team_id)=c.team_id
        WHERE landmark=1200 AND l.fold IN ('train','validation')
    """,
        [str(replay / "landmarks.parquet")],
    )
    con.execute("""
        CREATE TEMP TABLE acquisitions AS
        SELECT l.match_id,l.player_slot,p.item_id,max(p.buy_time) AS acquired_at
        FROM observations l JOIN purchases p USING(match_id,player_slot)
        WHERE p.buy_time<1200 AND list_contains(l.owned_items,p.item_id)
        GROUP BY l.match_id,l.player_slot,p.item_id
    """)
    con.execute("""
        CREATE TEMP TABLE frozen AS
        SELECT o.*, a.current_items,a.acquired_times
        FROM observations o JOIN (
            SELECT match_id,player_slot,list(item_id ORDER BY item_id) AS current_items,
                   list(acquired_at ORDER BY item_id) AS acquired_times
            FROM acquisitions GROUP BY match_id,player_slot
        ) a USING(match_id,player_slot)
    """)
    duplicate = con.execute(
        "SELECT count(*) FROM (SELECT hero_id,match_id,count(*) n FROM frozen GROUP BY ALL HAVING n>1)"
    ).fetchone()[0]
    mismatch = con.execute(
        "SELECT count(*) FROM frozen WHERE list_sort(owned_items)!=current_items OR len(enemy_heroes)!=6 OR list_max(acquired_times)>=1200"
    ).fetchone()[0]
    if duplicate or mismatch:
        raise ValueError(
            f"Invalid current inventory/composition rows: {duplicate=}, {mismatch=}"
        )
    con.execute(
        "COPY (SELECT * FROM frozen ORDER BY hero_id,start_time,match_id) TO ? (FORMAT PARQUET)",
        [str(output / "observations.parquet")],
    )
    heroes = {hero: save_hero(con, catalog, hero, output) for hero in HEROES}
    chronology = con.execute(
        "SELECT partition,min(start_time)::VARCHAR,max(start_time)::VARCHAR,count(DISTINCT match_id) FROM frozen GROUP BY partition ORDER BY min(start_time)"
    ).fetchall()
    overlap = con.execute(
        "SELECT count(*) FROM (SELECT match_id,count(DISTINCT partition) n FROM frozen GROUP BY match_id HAVING n>1)"
    ).fetchone()[0]
    if overlap:
        raise ValueError("Whole-match partitions overlap")
    assets = {
        str(item): {
            "name": catalog.names[item],
            "cost": catalog.costs[item],
            "ancestors": sorted(catalog.ancestors[item]),
        }
        for item in catalog.ids
    }
    write_json(output / "catalog.json", assets)
    manifest = {
        "source": str(source),
        "source_manifest_sha256": fingerprint(source / "manifest.json"),
        "replay_sha256": previous["landmarks_sha256"],
        "heroes": heroes,
        "chronology": chronology,
        "duplicate_hero_matches": duplicate,
        "inventory_or_composition_mismatches": mismatch,
        "cross_partition_matches": overlap,
        "build_labels_used": False,
        "test_fold_read": False,
        "source_sha256": fingerprint(Path(__file__)),
        "files": {
            path.name: fingerprint(path)
            for path in sorted(output.iterdir())
            if path.is_file()
        },
    }
    write_json(output / "manifest.json", manifest)
    con.close()
    print(json.dumps({"heroes": heroes, "chronology": chronology}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    prepare(args.replay, args.output)
