"""Freeze all identity nominations and purchase paths before later evaluation."""

from __future__ import annotations

import hashlib
import json
import time
from operator import itemgetter
from pathlib import Path

from deadlock_build_sync.mechanics import ItemGraph
from threadpoolctl import threadpool_limits

from experiments.core_discovery.data import HeroData, load_hero, write_json
from experiments.core_discovery.quality import evaluate_core, rejection_reasons
from experiments.identity_paths.config import ARMS, SCHEMA_VERSION
from experiments.identity_paths.grouping import consolidate
from experiments.identity_paths.mining import mine
from experiments.identity_paths.orders import choose_order
from experiments.identity_paths.purchase_data import (
    attach_windows,
    connect_events,
    hero_events,
)
from experiments.identity_paths.storage import (
    producer_hashes,
    read_json,
    source_hashes,
    verify_data,
    verify_original_assets,
)
from experiments.identity_paths.tactics import explain
from experiments.qdfm.extract import HEROES, fingerprint


def identity_id(hero: int, items: list[int]) -> str:
    digest = hashlib.sha256(json.dumps(sorted(items)).encode()).hexdigest()[:16]
    return f"{hero}-{digest}"


def select(candidates: list[dict], groups: list[list[int]] | None = None) -> list[int]:
    eligible = sorted(
        (
            index
            for index, row in enumerate(candidates)
            if not row["selection_rejections"]
        ),
        key=lambda index: (
            -candidates[index]["selection"]["adjusted"]["lower_95"],
            -candidates[index]["selection"]["owners"],
            candidates[index]["items"],
        ),
    )
    if groups is None:
        return eligible[:3]
    membership = {
        index: group for group, members in enumerate(groups) for index in members
    }
    selected, used = [], set()
    for index in eligible:
        if membership[index] not in used:
            selected.append(index)
            used.add(membership[index])
    return selected[:3]


def discover_hero(data: HeroData, catalog: dict) -> dict:
    started = time.monotonic()
    discovery = data.mask("discovery")
    mining = mine(data.matrix[discovery], data.times[discovery], data.items, catalog)
    mine_seconds = time.monotonic() - started
    candidates = sorted(
        (row for row in mining["candidates"] if len(row["items"]) >= 4),
        key=itemgetter("items"),
    )
    started = time.monotonic()
    grouping = consolidate(candidates, data.matrix[discovery], data.items)
    group_seconds = time.monotonic() - started
    for row in candidates:
        row["identity_id"] = identity_id(data.hero, row["items"])
        row["selection"] = evaluate_core(data, tuple(row["items"]), "selection")
        row["selection_rejections"] = rejection_reasons(row["selection"])
    return {
        "sizes": mining["sizes"],
        "seeds": [row for row in mining["candidates"] if len(row["items"]) == 3],
        "candidates": candidates,
        "grouping": grouping,
        "mine_seconds": mine_seconds,
        "group_seconds": group_seconds,
        "selected": {
            ARMS[0]: select(candidates),
            ARMS[1]: select(candidates, grouping["groups"]),
        },
    }


def nominate(
    report: dict,
    data: HeroData,
    hero: dict,
    assets: list[dict],
    graph: ItemGraph,
    events: dict,
) -> list[dict]:
    nominations, cache = [], {}
    for arm in ARMS:
        indices = report["selected"][ARMS[0] if arm == ARMS[0] else ARMS[1]]
        method = "prefixspan" if arm == ARMS[2] else "pairwise"
        for index in indices:
            row = report["candidates"][index]
            key = (row["identity_id"], method)
            if key not in cache:
                started = time.monotonic()
                path = choose_order(data, row["items"], method, graph)
                attach_windows(path, data, row["items"], events)
                path["runtime_s"] = time.monotonic() - started
                cache[key] = path
            group = next(
                members for members in report["grouping"]["groups"] if index in members
            )
            nominations.append({
                **row,
                "hero_id": data.hero,
                "hero": HEROES[data.hero][0],
                "arm": arm,
                "group_candidates": [
                    report["candidates"][member]["items"] for member in group
                ],
                "tactics": explain(hero, row["items"], assets),
                "path": cache[key],
            })
    return nominations


def run(directory: Path, output: Path) -> None:
    data_manifest = verify_data(directory)
    source = Path(data_manifest["source"])
    if fingerprint(source / "manifest.json") != data_manifest["source_manifest_sha256"]:
        raise ValueError("Original source manifest changed")
    hashes = source_hashes(source)
    recorded = read_json(source / "manifest.json")["sources"]["source_sha256"]
    verify_original_assets(source, recorded)
    output.mkdir(parents=True, exist_ok=False)
    catalog = read_json(directory / "catalog.json")
    assets = read_json(source / "raw/items-all.json")
    graph = ItemGraph.from_assets(read_json(source / "raw/items.json"))
    heroes = {row["id"]: row for row in read_json(source / "raw/heroes.json")}
    con = connect_events(directory, source)
    nominations, names = [], []
    try:
        with threadpool_limits(limits=1):
            for hero in HEROES:
                print(f"Discovering {HEROES[hero][0]}", flush=True)
                data = load_hero(directory, hero)
                report = discover_hero(data, catalog)
                rows = nominate(
                    report, data, heroes[hero], assets, graph, hero_events(con, hero)
                )
                nominations.extend(rows)
                name = f"hero-{hero}.json"
                write_json(output / name, report)
                names.append(name)
                print(
                    f"{HEROES[hero][0]}: {len(report['candidates'])} candidates, {len(report['grouping']['groups'])} groups, {len(rows)} arm nominations",
                    flush=True,
                )
    finally:
        con.close()
    write_json(output / "nominations.json", nominations)
    names.append("nominations.json")
    write_json(
        output / "manifest.json",
        {
            "schema_version": SCHEMA_VERSION,
            "directory": str(directory.resolve()),
            "data_manifest_sha256": fingerprint(directory / "manifest.json"),
            "source_sha256": hashes,
            "producer_sha256": producer_hashes(),
            "files": {name: fingerprint(output / name) for name in names},
            "arms": list(ARMS),
            "validation_evaluated": False,
            "test_evaluated": False,
            "existing_identities_used": False,
            "production_promotion": False,
        },
    )
    print(f"Frozen {len(nominations)} arm nominations", flush=True)
