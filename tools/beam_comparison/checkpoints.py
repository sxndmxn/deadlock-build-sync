"""Compare pure beam routes at fixed ownership checkpoints on captured matches."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from deadlock_build_sync.artifacts import atomic_write_json
from deadlock_build_sync.build_support import SUPPORT
from deadlock_build_sync.guide_generator import BEAM_SETTINGS
from deadlock_build_sync.offline import discovery_export, production_evidence
from deadlock_build_sync.offline.beam_model import load_beam_model
from deadlock_build_sync.offline.beam_nomination import beam_purchase_order
from deadlock_build_sync.offline.beam_search import GroupSearchRequest, search_group
from deadlock_build_sync.offline.beam_snapshot import beam_implementation_record
from deadlock_build_sync.offline.beam_support import (
    BeamOwnership,
    core_state_statistics,
    wealth_state,
)
from deadlock_build_sync.offline.config import RunPaths
from deadlock_build_sync.offline.discovery_artifacts import freeze_purchase_guide
from deadlock_build_sync.offline.discovery_data import (
    build_hero_discovery_data,
    load_landmark_rows,
    load_purchase_histories,
    prepare_discovery_partitions,
)
from deadlock_build_sync.offline.discovery_quality import evaluate_core
from deadlock_build_sync.snapshot import sha256_json
from deadlock_build_sync.value_validation import (
    integer,
    require_object_dict,
    require_object_list,
    require_object_rows,
)

if TYPE_CHECKING:
    import duckdb

    from deadlock_build_sync.mechanics import ItemGraph
    from deadlock_build_sync.offline.beam_search import GroupSearchResult
    from deadlock_build_sync.offline.discovery_data import HeroDiscoveryData
    from deadlock_build_sync.offline.discovery_types import NominatedCoreBuild
    from deadlock_build_sync.offline.production_sources import _HeroExportContext

CHECKPOINTS = (1200, 1800)
DISPLAY_LIMIT = 3


def load_checkpoint_data(
    connection: duckdb.DuckDBPyConnection,
    hero: int,
    context: _HeroExportContext,
    seconds: int,
) -> HeroDiscoveryData:
    rows = load_landmark_rows(connection, hero, ownership_before_seconds=seconds)
    histories = load_purchase_histories(
        connection, hero, ownership_before_seconds=seconds
    )
    return build_hero_discovery_data(
        hero,
        [
            row
            for row in rows
            if context.minimum_badge <= row[6] <= context.maximum_badge
        ],
        histories,
        context.item_graph,
        ownership_before_seconds=seconds,
    )


def nominate_routes(
    connection: duckdb.DuckDBPyConnection,
    data: HeroDiscoveryData,
    graph: ItemGraph,
    result: GroupSearchResult,
) -> tuple[list[dict[str, object]], dict[str, int]]:
    selected: list[dict[str, object]] = []
    admitted: set[tuple[int, ...]] = set()
    rejected: Counter[str] = Counter()
    for route in result.routes:
        if route.core in admitted:
            continue
        order = beam_purchase_order(data, route, graph)
        if not order["admitted_before_validation"]:
            rejected["Insufficient complete purchase-order support"] += 1
            continue
        row: NominatedCoreBuild = {"items": list(route.core), "path": order}
        guide = freeze_purchase_guide(
            connection, data, row, graph, exact_path=route.path
        )
        if not guide["ready"]:
            rejected[guide.get("reason") or "Incomplete guide"] += 1
            continue
        selected.append({"route": asdict(route), "order": order, "guide": guide})
        admitted.add(route.core)
        if len(selected) == DISPLAY_LIMIT:
            break
    return selected, dict(rejected)


def population_counts(data: HeroDiscoveryData) -> dict[str, object]:
    return {
        fold: {
            "matches": int(data.fold_mask(fold).sum()),
            "known_state": int(
                (data.fold_mask(fold) & np.isfinite(data.relative_wealth)).sum()
            ),
        }
        for fold in ("discovery", "selection", "validation")
    }


def nominate_hero(
    hero: dict[str, object], context: _HeroExportContext
) -> dict[str, object]:
    started = time.monotonic()
    records: list[dict[str, object]] = []
    hero_id = integer(hero["id"])
    # The producer opens captured data read-only and uses temporary partitions.
    with discovery_export._open_discovery_database(context) as connection:  # ruff: ignore[private-member-access]
        prepare_discovery_partitions(connection)
        initial = load_checkpoint_data(connection, hero_id, context, CHECKPOINTS[0])
        model = load_beam_model(
            connection, initial, context.minimum_badge, context.maximum_badge
        )
        model_hash = sha256_json({
            "prior": model.prior,
            "cells": sorted(model.cells.items()),
        })
        for seconds in CHECKPOINTS:
            data = (
                initial
                if seconds == CHECKPOINTS[0]
                else load_checkpoint_data(connection, hero_id, context, seconds)
            )
            for state in (1, 0, 2):
                request = GroupSearchRequest(
                    context.item_graph,
                    model,
                    BeamOwnership(data, context.item_graph, state),
                    {},
                    None,
                    state,
                    data.items,
                )
                search = search_group(request)
                selected, rejected = nominate_routes(
                    connection, data, context.item_graph, search
                )
                records.append({
                    "ownership_before_seconds": seconds,
                    "state": state,
                    "population": population_counts(data),
                    "candidate_items": list(data.items),
                    "search": asdict(search),
                    "selected": selected,
                    "rejected_before_display_limit": rejected,
                })
    return {
        "hero_id": hero_id,
        "hero_name": hero["name"],
        "model_sha256": model_hash,
        "records": records,
        "elapsed_seconds": time.monotonic() - started,
    }


def evaluate_selected(
    data: HeroDiscoveryData, record: dict[str, object]
) -> dict[str, object]:
    state = integer(record["state"])
    validation = data.fold_mask("validation")
    matched = np.asarray(
        [wealth_state(value) == state for value in data.relative_wealth], dtype=bool
    )
    covered = np.zeros(len(data.matches), dtype=bool)
    estimates: list[dict[str, object]] = []
    for selected in require_object_rows(record["selected"]):
        route = require_object_dict(selected["route"])
        core = tuple(integer(item) for item in require_object_list(route["core"]))
        mask = np.asarray(
            [set(core).issubset(owned) for owned in data.inventories], dtype=bool
        )
        covered |= mask
        estimates.append({
            "core": list(core),
            "state_evidence": core_state_statistics(data, core, state),
            "all_states_validation": evaluate_core(data, core, "validation"),
        })
    return {
        "estimates": estimates,
        "validation_matches": int(validation.sum()),
        "validation_state_matches": int((validation & matched).sum()),
        "covered_validation_matches": int((validation & covered).sum()),
        "covered_validation_state_matches": int((validation & matched & covered).sum()),
    }


def evaluate_hero(
    hero: dict[str, object], context: _HeroExportContext
) -> dict[str, object]:
    evaluations: list[dict[str, object]] = []
    with discovery_export._open_discovery_database(context) as connection:  # ruff: ignore[private-member-access]
        prepare_discovery_partitions(connection)
        for seconds in CHECKPOINTS:
            data = load_checkpoint_data(
                connection, integer(hero["hero_id"]), context, seconds
            )
            evaluations.extend(
                {
                    "ownership_before_seconds": seconds,
                    "state": record["state"],
                    **evaluate_selected(data, record),
                }
                for record in require_object_rows(hero["records"])
                if record["ownership_before_seconds"] == seconds
            )
    return {"hero_id": hero["hero_id"], "records": evaluations}


def source_identity(source: Path) -> dict[str, str]:
    names = (
        "manifest.json",
        "raw/analysis.duckdb",
        "raw/items.json",
        "raw/items-all.json",
        "raw/heroes.json",
    )
    result = {}
    for name in names:
        with (source / name).open("rb") as handle:
            result[name] = hashlib.file_digest(handle, "sha256").hexdigest()
    return result


def experiment_implementation() -> dict[str, object]:
    return {
        "product": beam_implementation_record(),
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--heroes", type=int, nargs="+")
    parser.add_argument("--phase", choices=("nominate", "evaluate"), required=True)
    args = parser.parse_args()
    source = args.source.resolve()
    paths = RunPaths(
        source.parent.parent,
        source,
        source / "raw",
        source / "data",
        source / "tables",
        source / "figures",
        source / "raw/api",
    )
    manifest = require_object_dict(json.loads((source / "manifest.json").read_text()))
    context = production_evidence._export_context(  # ruff: ignore[private-member-access]
        paths, require_object_dict(manifest["cohort"]), manifest
    )
    identity = source_identity(source)
    implementation = experiment_implementation()
    frozen_path = args.output / "frozen.json"
    args.output.mkdir(parents=True, exist_ok=True)
    if args.phase == "nominate":
        heroes = require_object_rows(
            json.loads((source / "raw/heroes.json").read_text())
        )
        heroes = [
            hero
            for hero in heroes
            if not args.heroes or integer(hero["id"]) in args.heroes
        ]
        records = []
        for hero in heroes:
            records.append(nominate_hero(hero, context))
            atomic_write_json(args.output / f"hero-{hero['id']}.json", records[-1])
            sys.stdout.write(
                f"Nominated {hero['name']}: {records[-1]['elapsed_seconds']:.2f} seconds\n"
            )
            sys.stdout.flush()
        atomic_write_json(
            frozen_path,
            {
                "schema": 1,
                "method": "pure-state-aware-beam16",
                "source": identity,
                "implementation": implementation,
                "cohort": manifest["cohort"],
                "settings": {
                    **BEAM_SETTINGS,
                    "ownership_before_seconds": list(CHECKPOINTS),
                    "group_restrictions": False,
                    "maximum_owned_items": 6,
                    "display_limit_per_state": DISPLAY_LIMIT,
                    "admission": asdict(SUPPORT),
                },
                "heroes": records,
            },
        )
    else:
        frozen = require_object_dict(json.loads(frozen_path.read_text()))
        if frozen["source"] != identity or frozen["implementation"] != implementation:
            raise ValueError(
                "Captured source or implementation differs from the frozen experiment"
            )
        results = []
        for hero in require_object_rows(frozen["heroes"]):
            results.append(evaluate_hero(hero, context))
            sys.stdout.write(f"Evaluated {hero['hero_name']}\n")
            sys.stdout.flush()
        atomic_write_json(
            args.output / "evaluation.json",
            {
                "frozen_sha256": hashlib.sha256(frozen_path.read_bytes()).hexdigest(),
                "heroes": results,
            },
        )


if __name__ == "__main__":
    main()
