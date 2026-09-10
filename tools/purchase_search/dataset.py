"""Prepare partition-specific observations without changing source data."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import duckdb
import numpy as np

from deadlock_build_sync.mechanics import ItemGraph
from deadlock_build_sync.offline.inventory_reconstruction import InventoryTimeline

from .freeze import verify_frozen
from .records import Catalog

SQL_DIRECTORY = Path(__file__).with_name("sql")
DEFAULT_SOURCE = (
    Path.home() / ".local/state/deadlock-build-sync/offline/results/20260909T001949Z"
)
DEFAULT_OUTPUT = Path("generated/purchase-guide-search/data-corrected")
History = list[tuple[int, int, int]]


@dataclass(frozen=True)
class PreparationRequest:
    source: Path
    output: Path
    partition: str
    sample_size: int = 96
    freshness: int = 120
    frozen: Path | None = None


@dataclass(frozen=True)
class LandmarkContext:
    partition: str
    freshness: int
    catalog: Catalog
    output: Path


def read_sql(name: str) -> str:
    return (SQL_DIRECTORY / name).read_text(encoding="utf-8")


def load_catalog(source: Path) -> Catalog:
    assets = cast(
        "list[dict[str, object]]",
        json.loads((source / "raw/items.json").read_text(encoding="utf-8")),
    )
    return Catalog.from_graph(ItemGraph.from_assets(assets))


def source_identity(
    source: Path, sample_size: int, freshness: int
) -> dict[str, object]:
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    patches = json.loads((source / "raw/patches.json").read_text(encoding="utf-8"))
    patch = max(
        row["pub_date"]
        for row in patches
        if row["pub_date"] <= manifest["cohort"]["as_of"]
    )
    specification = {
        "manifest": manifest,
        "patch": patch,
        "sample_size": sample_size,
        "freshness": freshness,
        "wealth_bin_width": 4000,
        "wealth_bins": 12,
        "sql": {
            path.name: path.read_text(encoding="utf-8")
            for path in sorted(SQL_DIRECTORY.glob("*.sql"))
        },
    }
    fingerprint = hashlib.sha256(
        json.dumps(specification, sort_keys=True).encode()
    ).hexdigest()
    return {
        "source": str(source.resolve()),
        "fingerprint": fingerprint,
        "patch": patch + ":" + manifest["sources"]["source_sha256"]["items.json"][:16],
        "sample_size": sample_size,
        "freshness": freshness,
        "source_snapshot_version": manifest["extraction"]["source_snapshot_version"],
    }


def collect_histories(
    connection: duckdb.DuckDBPyConnection, partition: str, hero: int
) -> dict[tuple[int, int], History]:
    rows = connection.execute(
        read_sql("select_histories.sql"), {"partition": partition, "hero": hero}
    ).fetchall()
    histories: dict[tuple[int, int], History] = defaultdict(list)
    for match, slot, item, bought, sold in rows:
        histories[int(match), int(slot)].append((
            int(item),
            int(bought),
            int(sold or 0),
        ))
    return histories


def observed_suffix(history: History, clock: int, index: dict[int, int]) -> list[int]:
    purchases = [(item, bought) for item, bought, _ in history if bought >= clock]
    timestamps = Counter(bought for _, bought in purchases)
    suffix = []
    for item, bought in purchases:
        if timestamps[bought] != 1 or item not in index or len(suffix) == 4:
            break
        suffix.append(index[item])
    return suffix


def prepare_queries(
    rows: list[tuple[object, ...]],
    histories: dict[tuple[int, int], History],
    catalog: Catalog,
) -> tuple[list[dict[str, object]], int]:
    queries = []
    rejected = 0
    index = {item: position for position, item in enumerate(catalog.item_ids)}
    for hero, match, slot, clock, wealth, relative, item, won in rows:
        history = histories[int(match), int(slot)]
        owned = InventoryTimeline(history, catalog.graph.components).before(int(clock))
        if len(set(owned)) != len(owned) or any(
            value not in index for value in (*owned, int(item))
        ):
            rejected += 1
            continue
        queries.append({
            "hero": int(hero),
            "match": int(match),
            "slot": int(slot),
            "clock": int(clock),
            "net_worth": int(wealth),
            "relative_state": int(relative),
            "owned": hex(catalog.mask(owned)),
            "action": index[int(item)],
            "won": bool(won),
            "observed_suffix": observed_suffix(history, int(clock), index),
        })
    return queries, rejected


def prepare_landmarks(
    connection: duckdb.DuckDBPyConnection,
    hero: int,
    histories: dict[tuple[int, int], History],
    context: LandmarkContext,
) -> dict[str, int]:
    rows = connection.execute(
        read_sql("select_landmarks.sql"),
        {
            "partition": context.partition,
            "hero": hero,
            "freshness": context.freshness,
        },
    ).fetchall()
    index = {item: position for position, item in enumerate(context.catalog.item_ids)}
    matrices: dict[int, list[tuple[int, bool, int, int, tuple[int, ...]]]] = (
        defaultdict(list)
    )
    current_actor = None
    timeline = None
    rejected = 0
    for match, slot, clock, won, relative, wealth in rows:
        actor = int(match), int(slot)
        if actor != current_actor:
            timeline = InventoryTimeline(
                histories.get(actor, []), context.catalog.graph.components
            )
            current_actor = actor
        if timeline is None:
            raise RuntimeError("Inventory timeline is missing")
        owned = timeline.before(int(clock))
        if len(set(owned)) != len(owned) or any(item not in index for item in owned):
            rejected += 1
            continue
        matrices[int(clock)].append((
            int(match),
            bool(won),
            int(relative),
            int(wealth or -1),
            owned,
        ))
    counts = {"rejected_inventories": rejected}
    for clock, records in matrices.items():
        matrix = np.zeros((len(records), len(index)), dtype=np.bool_)
        for offset, row in enumerate(records):
            matrix[offset, [index[item] for item in row[4]]] = True
        np.savez_compressed(
            context.output / f"{hero}-{clock}.npz",
            matrix=matrix,
            matches=np.asarray([row[0] for row in records], dtype=np.int64),
            won=np.asarray([row[1] for row in records], dtype=np.bool_),
            relative_state=np.asarray([row[2] for row in records], dtype=np.int8),
            net_worth=np.asarray([row[3] for row in records], dtype=np.int32),
        )
        counts[str(clock)] = len(records)
    return counts


def prepare_heroes(
    connection: duckdb.DuckDBPyConnection,
    request: PreparationRequest,
    catalog: Catalog,
    samples: list[tuple[object, ...]],
    hero_counts: list[tuple[int, int, int]],
) -> tuple[list[dict[str, object]], dict[str, dict[str, int]], int]:
    queries = []
    landmark_counts = {}
    rejected_queries = 0
    context = LandmarkContext(
        request.partition,
        request.freshness,
        catalog,
        request.output / request.partition,
    )
    for hero, _, _ in hero_counts:
        histories = collect_histories(connection, request.partition, hero)
        hero_queries, rejected = prepare_queries(
            [row for row in samples if row[0] == hero], histories, catalog
        )
        queries.extend(hero_queries)
        rejected_queries += rejected
        landmark_counts[str(hero)] = prepare_landmarks(
            connection, hero, histories, context
        )
        sys.stdout.write(
            f"Prepared {request.partition} hero {hero}: {len(hero_queries)} queries\n"
        )
        sys.stdout.flush()
    return queries, landmark_counts, rejected_queries


def prepare_partition(request: PreparationRequest) -> Path:
    if request.partition not in {"train", "validation", "test"}:
        raise ValueError("Unknown data partition")
    destination = request.output / request.partition
    identity = source_identity(request.source, request.sample_size, request.freshness)
    if request.partition == "test":
        verify_frozen(request.frozen, str(identity["fingerprint"]))
    cache_manifest = destination / "manifest.json"
    if cache_manifest.exists():
        cached = json.loads(cache_manifest.read_text(encoding="utf-8"))
        if cached["fingerprint"] != identity["fingerprint"]:
            raise ValueError("The existing data cache has an incompatible fingerprint")
        return destination
    destination.mkdir(parents=True, exist_ok=True)
    catalog = load_catalog(request.source)
    started = time.perf_counter()
    with duckdb.connect(
        str(request.source / "raw/analysis.duckdb"),
        read_only=True,
        config={"threads": 2, "memory_limit": "1GiB"},
    ) as connection:
        connection.execute(
            read_sql("create_eligible_matches.sql"), {"partition": request.partition}
        )
        connection.execute(
            read_sql("create_observations.sql"),
            {"partition": request.partition, "freshness": request.freshness},
        )
        samples = connection.execute(
            read_sql("select_query_sample.sql"), {"sample_size": request.sample_size}
        ).fetchall()
        statistics = {
            **identity,
            "partition": request.partition,
            "item_ids": catalog.item_ids,
            "item_counts": connection.execute(
                read_sql("select_item_counts.sql")
            ).fetchall(),
            "state_counts": connection.execute(
                read_sql("select_state_counts.sql")
            ).fetchall(),
            "hero_counts": connection.execute(
                "SELECT p.hero_id, count(*), sum(p.won::INTEGER) FROM player_matches p JOIN experiment_matches e USING(match_id) GROUP BY p.hero_id ORDER BY p.hero_id",
            ).fetchall(),
            "eligible_matches": connection.execute(
                "SELECT count(*) FROM experiment_matches"
            ).fetchone()[0],
            "excluded_matches": connection.execute(
                "SELECT count(*) FROM match_folds WHERE fold = ? AND match_id NOT IN (SELECT match_id FROM experiment_matches)",
                [request.partition],
            ).fetchone()[0],
        }
        (destination / "statistics.json").write_text(
            json.dumps(statistics) + "\n", encoding="utf-8"
        )
        queries, landmark_counts, rejected_queries = prepare_heroes(
            connection, request, catalog, samples, statistics["hero_counts"]
        )
    (destination / "queries.json").write_text(
        json.dumps(queries) + "\n", encoding="utf-8"
    )
    result = {
        **identity,
        "partition": request.partition,
        "heroes": len(statistics["hero_counts"]),
        "queries": len(queries),
        "eligible_matches": statistics["eligible_matches"],
        "excluded_matches": statistics["excluded_matches"],
        "rejected_queries": rejected_queries,
        "landmark_counts": landmark_counts,
        "elapsed_seconds": time.perf_counter() - started,
        "frozen_specification_sha256": hashlib.sha256(
            request.frozen.read_bytes()
        ).hexdigest()
        if request.frozen
        else None,
    }
    cache_manifest.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prepare isolated purchase-search evidence"
    )
    parser.add_argument("partition", choices=("train", "validation", "test"))
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--sample-size", type=int, default=96)
    parser.add_argument("--frozen", type=Path)
    arguments = parser.parse_args()
    destination = prepare_partition(
        PreparationRequest(
            arguments.source,
            arguments.output,
            arguments.partition,
            sample_size=arguments.sample_size,
            frozen=arguments.frozen,
        )
    )
    sys.stdout.write(str(destination) + "\n")


if __name__ == "__main__":
    main()
