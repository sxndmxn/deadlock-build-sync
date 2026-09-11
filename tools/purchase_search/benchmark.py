"""Compare search methods on fixed guide and held-out decision queries."""

from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from dataclasses import asdict, dataclass
from itertools import combinations
from pathlib import Path

import numpy as np

from deadlock_build_sync.mechanics_assets import BASE_INVENTORY_SLOTS, MAX_ACTIVE_ITEMS

from .dataset import DEFAULT_OUTPUT, DEFAULT_SOURCE, load_catalog
from .evidence import JointSupport, OwnershipEvidence
from .freeze import verify_benchmark
from .model import ItemModel
from .records import (
    GUIDE_CHECKPOINTS,
    Catalog,
    CombinationConfig,
    Query,
    ScoringConfig,
    SearchConfig,
    SearchResult,
    SearchState,
)
from .search import (
    SearchGuidance,
    inventory_distance,
    search,
    transition,
    validate_path,
)


def result_record(
    catalog: Catalog, query: Query, result: SearchResult
) -> dict[str, object]:
    for path in result.paths:
        validate_path(catalog, query, path)
    distances = [
        inventory_distance(first.owned & ~query.owned, second.owned & ~query.owned)
        for first, second in combinations(result.paths, 2)
    ]
    return {
        "hero": query.hero,
        "relative_state": query.relative_state,
        "budget": query.budget,
        "initial_net_worth": query.net_worth,
        "initial_cash": query.cash,
        "initial_owned": hex(query.owned),
        "flex_slots": query.flex_slots,
        "initial_inventory_eligible": (
            query.owned.bit_count() <= BASE_INVENTORY_SLOTS + query.flex_slots
            and (query.owned & catalog.active_mask).bit_count() <= MAX_ACTIVE_ITEMS
        ),
        "valid": True,
        "abstained": not result.paths,
        "search_seconds": result.elapsed_seconds,
        "expansions": result.expansions,
        "duplicate_states": result.duplicate_states,
        "diversity": sum(distances) / len(distances) if distances else 0.0,
        "distinct_first_actions": len({path.path[0] for path in result.paths}),
        "paths": [
            {
                "path": path.path,
                "path_names": [catalog.names[item] for item in path.path],
                "owned": hex(path.owned),
                "owned_names": catalog.item_names(path.owned),
                "spent": path.spent,
                "score": path.score,
                "minimum_item_support": path.minimum_support,
            }
            for path in result.paths
        ],
    }


@dataclass(frozen=True)
class BenchmarkContext:
    catalog: Catalog
    model: ItemModel
    data: Path
    partition: str
    heroes: tuple[int, ...]
    structures: dict[str, object]
    joint_support: int = 0


def guide_records(
    context: BenchmarkContext, config: SearchConfig
) -> list[dict[str, object]]:
    training = OwnershipEvidence(context.data / "train")
    heldout = OwnershipEvidence(context.data / context.partition)
    records = []
    for hero in context.heroes:
        for budget, checkpoint in GUIDE_CHECKPOINTS:
            for relative_state in range(3):
                query = Query(
                    hero, context.model.patch, 800, relative_state, 800, budget
                )
                themes = tuple(
                    int(value, 16)
                    for value in context.structures
                    .get(str(hero), {})
                    .get(config.method, {})
                    .get("themes", [])
                )
                support = (
                    JointSupport(
                        training,
                        context.catalog,
                        query,
                        checkpoint,
                        CombinationConfig(context.joint_support, 3),
                    )
                    if context.joint_support
                    else None
                )
                result = search(
                    context.catalog,
                    context.model,
                    query,
                    config,
                    SearchGuidance(themes, support),
                )
                row = result_record(context.catalog, query, result)
                row["checkpoint"] = checkpoint
                for path in row["paths"]:
                    owned = int(path["owned"], 16)
                    path["training"] = training.counts(
                        hero, checkpoint, owned, relative_state
                    )
                    path["heldout"] = heldout.counts(
                        hero, checkpoint, owned, relative_state
                    )
                records.append(row)
    return records


def decision_records(
    context: BenchmarkContext, config: SearchConfig, limit: int
) -> list[dict[str, object]]:
    observations = json.loads(
        (context.data / context.partition / "queries.json").read_text(encoding="utf-8")
    )
    records = []
    counts = dict.fromkeys(context.heroes, 0)
    training = OwnershipEvidence(context.data / "train")
    for observation in observations:
        hero = observation["hero"]
        if hero not in counts or counts[hero] >= limit:
            continue
        counts[hero] += 1
        query = Query(
            hero,
            context.model.patch,
            observation["net_worth"],
            observation["relative_state"],
            min(1600, observation["net_worth"]),
            6400,
            int(observation["owned"], 16),
        )
        themes = tuple(
            int(value, 16)
            for value in context.structures
            .get(str(hero), {})
            .get(config.method, {})
            .get("themes", [])
        )
        checkpoint = (
            600 if query.net_worth < 8000 else 1201 if query.net_worth < 20000 else 1801
        )
        support = (
            JointSupport(
                training,
                context.catalog,
                query,
                checkpoint,
                CombinationConfig(context.joint_support, 1),
            )
            if context.joint_support
            else None
        )
        result = search(
            context.catalog,
            context.model,
            query,
            config,
            SearchGuidance(themes, support),
        )
        row = result_record(context.catalog, query, result)
        first_actions = [path.path[0] for path in result.paths]
        observed = transition(
            context.catalog,
            context.model,
            query,
            SearchState.initial(query),
            observation["action"],
        )
        row.update({
            "match": observation["match"],
            "won": observation["won"],
            "observed_action": observation["action"],
            "observed_action_permitted": bool(
                row["initial_inventory_eligible"]
                and observed is not None
                and (support is None or support.complete(observed.owned))
            ),
            "top1_agreement": bool(
                first_actions and first_actions[0] == observation["action"]
            ),
            "alternative_agreement": observation["action"] in first_actions,
            "prefix_two_eligible": len(observation["observed_suffix"]) >= 2,
            "prefix_two_agreement": bool(
                result.paths
                and len(result.paths[0].path) >= 2
                and list(result.paths[0].path[:2]) == observation["observed_suffix"][:2]
            ),
        })
        records.append(row)
    return records


def summarize(records: list[dict[str, object]], mode: str) -> dict[str, object]:
    count = len(records)
    times = np.asarray([row["search_seconds"] for row in records])
    result = {
        "queries": count,
        "valid_queries": sum(row["valid"] for row in records),
        "validated_paths": sum(len(row["paths"]) for row in records),
        "validated_actions": sum(
            len(path["path"]) for row in records for path in row["paths"]
        ),
        "abstention_rate": sum(row["abstained"] for row in records) / max(1, count),
        "median_ms": float(np.median(times) * 1000),
        "p95_ms": float(np.quantile(times, 0.95) * 1000),
        "total_search_seconds": float(times.sum()),
        "mean_expansions": float(np.mean([row["expansions"] for row in records])),
        "mean_duplicate_states": float(
            np.mean([row["duplicate_states"] for row in records])
        ),
        "mean_diversity": float(np.mean([row["diversity"] for row in records])),
        "mean_distinct_first_actions": float(
            np.mean([row["distinct_first_actions"] for row in records])
        ),
    }
    if mode == "decisions":
        result.update({
            "initial_inventory_eligible_share": sum(
                row.get("initial_inventory_eligible", True) for row in records
            )
            / max(1, count),
            "observed_action_permitted_share": sum(
                row.get("observed_action_permitted", False) for row in records
            )
            / max(1, count),
            "top1_agreement": sum(row["top1_agreement"] for row in records)
            / max(1, count),
            "alternative_agreement": sum(
                row["alternative_agreement"] for row in records
            )
            / max(1, count),
            "prefix_two_agreement": sum(row["prefix_two_agreement"] for row in records)
            / max(1, sum(row["prefix_two_eligible"] for row in records)),
        })
    else:
        result.update(summarize_guides(records))
    return result


def summarize_guides(records: list[dict[str, object]]) -> dict[str, object]:
    count = len(records)
    top_paths = [row["paths"][0] for row in records if row["paths"]]
    return {
        "mean_score": mean_or_none([path["score"] for path in top_paths]),
        "top1_training_support_100": sum(
            (path["training"]["owners"] or 0) >= 100 for path in top_paths
        )
        / max(1, count),
        "top1_heldout_support_30": sum(
            (path["heldout"]["owners"] or 0) >= 30 for path in top_paths
        )
        / max(1, count),
        "top1_heldout_support_100": sum(
            (path["heldout"]["owners"] or 0) >= 100 for path in top_paths
        )
        / max(1, count),
        "unavailable_top1_evidence": sum(
            not path["heldout"]["available"] for path in top_paths
        ),
        "median_top1_heldout_owners": median_or_none([
            path["heldout"]["owners"]
            for path in top_paths
            if path["heldout"]["available"]
        ]),
        "mean_final_items": mean_or_none([
            len(path["owned_names"]) for path in top_paths
        ]),
        "mean_budget_utilization": mean_or_none([
            row["paths"][0]["spent"] / row["budget"] for row in records if row["paths"]
        ]),
    }


def mean_or_none(values: list[float]) -> float | None:
    return float(np.mean(values)) if values else None


def median_or_none(values: list[float]) -> float | None:
    return float(np.median(values)) if values else None


def run_benchmark(arguments: argparse.Namespace) -> None:
    catalog = load_catalog(arguments.source)
    scoring = ScoringConfig(
        prior_strength=arguments.prior,
        cost_exponent=arguments.cost_exponent,
        state_aware=not arguments.stateless,
    )
    model = ItemModel.load(arguments.data / "train/statistics.json", scoring)
    if arguments.partition == "test":
        verify_benchmark(arguments, model.fingerprint)
    heroes = tuple(arguments.heroes or model.heroes)
    structures = {}
    if arguments.structures:
        structure_document = json.loads(
            arguments.structures.read_text(encoding="utf-8")
        )
        if structure_document["data_fingerprint"] != model.fingerprint:
            raise ValueError("Structure proposals do not match the training data")
        structures = structure_document["heroes"]
    context = BenchmarkContext(
        catalog,
        model,
        arguments.data,
        arguments.partition,
        heroes,
        structures,
        arguments.joint_support,
    )
    results = []
    for specification in arguments.methods:
        model.candidate_cache.clear()
        started = time.perf_counter()
        method, width = specification.split(":")
        config = SearchConfig(
            method,
            int(width),
            arguments.depth,
            arguments.alternatives,
            arguments.diversity,
        )
        if arguments.mode == "guides":
            records = guide_records(context, config)
        else:
            records = decision_records(context, config, arguments.sample_size)
        summary = summarize(records, arguments.mode)
        summary["total_evaluation_seconds"] = time.perf_counter() - started
        sys.stdout.write(specification + " " + json.dumps(summary) + "\n")
        sys.stdout.flush()
        results.append({
            "config": asdict(config),
            "summary": summary,
            "records": records,
        })
    document = {
        "mode": arguments.mode,
        "partition": arguments.partition,
        "patch": model.patch,
        "data_fingerprint": model.fingerprint,
        "scoring": asdict(scoring),
        "machine": platform.platform(),
        "heroes": heroes,
        "joint_support": arguments.joint_support,
        "frozen_specification": str(arguments.frozen) if arguments.frozen else None,
        "calibration": model.calibration(
            json.loads(
                (arguments.data / arguments.partition / "statistics.json").read_text(
                    encoding="utf-8"
                )
            )
        ),
        "results": results,
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare purchase-guide search methods"
    )
    parser.add_argument("mode", choices=("guides", "decisions"))
    parser.add_argument(
        "--partition", choices=("validation", "test"), default="validation"
    )
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--data", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--methods", nargs="+", default=["greedy:1", "beam:4", "beam:16", "diverse:16"]
    )
    parser.add_argument("--heroes", type=int, nargs="+")
    parser.add_argument("--depth", type=int, default=8)
    parser.add_argument("--alternatives", type=int, default=3)
    parser.add_argument("--sample-size", type=int, default=96)
    parser.add_argument("--diversity", type=float, default=0.02)
    parser.add_argument("--prior", type=float, default=100)
    parser.add_argument("--cost-exponent", type=float, default=0.5)
    parser.add_argument("--stateless", action="store_true")
    parser.add_argument("--structures", type=Path)
    parser.add_argument("--joint-support", type=int, default=0)
    parser.add_argument("--frozen", type=Path)
    run_benchmark(parser.parse_args())


if __name__ == "__main__":
    main()
