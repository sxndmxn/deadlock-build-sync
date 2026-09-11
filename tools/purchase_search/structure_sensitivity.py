"""Measure itemset and community sensitivity on validation inventories."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from itertools import combinations
from pathlib import Path

from .benchmark import BenchmarkContext, guide_records, summarize
from .dataset import DEFAULT_OUTPUT, DEFAULT_SOURCE, load_catalog
from .model import ItemModel
from .records import ScoringConfig, SearchConfig, mask_indices
from .structures import StructureConfig, prepare_structures


def community_pairs(packages: list[str]) -> set[tuple[int, int]]:
    return {
        pair
        for mask in packages
        for pair in combinations(mask_indices(int(mask, 16)), 2)
    }


def community_stability(first: dict[str, object], second: dict[str, object]) -> float:
    distances = []
    for hero, row in first["heroes"].items():
        original = community_pairs(row["leiden"]["packages"])
        changed = community_pairs(second["heroes"][hero]["leiden"]["packages"])
        union = original | changed
        distances.append(len(original & changed) / len(union) if union else 1.0)
    return sum(distances) / len(distances)


def structure_cases() -> tuple[tuple[str, str, StructureConfig], ...]:
    default = StructureConfig()
    return (
        ("default", "eclat", default),
        ("eclat_size_3", "eclat", replace(default, maximum_size=3)),
        ("eclat_size_6", "eclat", replace(default, maximum_size=6)),
        (
            "support_50",
            "eclat",
            replace(default, minimum_owners=50, support_fraction=0.005),
        ),
        (
            "support_200",
            "eclat",
            replace(default, minimum_owners=200, support_fraction=0.02),
        ),
        ("leiden_resolution_004", "leiden", replace(default, resolution=0.04)),
        ("leiden_resolution_016", "leiden", replace(default, resolution=0.16)),
        ("leiden_seed_23", "leiden", replace(default, seed=23)),
        ("leiden_seed_71", "leiden", replace(default, seed=71)),
    )


def run(arguments: argparse.Namespace) -> None:
    catalog = load_catalog(arguments.source)
    model = ItemModel.load(arguments.data / "train/statistics.json", ScoringConfig())
    results = []
    baseline = None
    arguments.output.mkdir(parents=True, exist_ok=True)
    for name, method, config in structure_cases():
        path = arguments.output / f"{name}-structures.json"
        prepare_structures(arguments.data, catalog, path, config)
        document = json.loads(path.read_text(encoding="utf-8"))
        baseline = baseline or document
        context = BenchmarkContext(
            catalog,
            model,
            arguments.data,
            "validation",
            model.heroes,
            document["heroes"],
            100,
        )
        records = guide_records(context, SearchConfig(method, 16))
        summary = {
            "case": name,
            "method": method,
            "config": document["config"],
            "preparation_seconds": document["elapsed_seconds"],
            "frequent_itemsets": sum(
                row["eclat"]["frequent_itemsets"] for row in document["heroes"].values()
            ),
            "communities": sum(
                row["leiden"]["communities"] for row in document["heroes"].values()
            ),
            "community_pair_jaccard": community_stability(baseline, document),
            "guide_summary": summarize(records, "guides"),
        }
        results.append(summary)
        (arguments.output / f"{name}-results.json").write_text(
            json.dumps({**summary, "records": records}, indent=2) + "\n",
            encoding="utf-8",
        )
        sys.stdout.write(json.dumps(summary) + "\n")
        sys.stdout.flush()
    (arguments.output / "summary.json").write_text(
        json.dumps(results, indent=2) + "\n", encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare validation structure settings"
    )
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--data", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args())


if __name__ == "__main__":
    main()
