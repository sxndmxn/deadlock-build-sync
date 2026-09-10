"""Build training-only itemset and community proposals for beam retention."""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import igraph
import leidenalg
import numpy as np

from .dataset import DEFAULT_OUTPUT, DEFAULT_SOURCE, load_catalog
from .evidence import bitset
from .records import Catalog, mask_indices
from .search import inventory_distance


@dataclass(frozen=True)
class StructureConfig:
    resolution: float = 0.08
    seed: int = 7
    minimum_owners: int = 100
    support_fraction: float = 0.01
    maximum_size: int = 4
    package_limit: int = 12
    maximum_cost: int = 19200


def mine_itemsets(
    columns: tuple[int, ...], minimum_support: int, maximum_size: int = 4
) -> list[tuple[int, int]]:
    """Intersect vertical transaction sets to enumerate frequent itemsets.

    Returns:
        Itemset masks and their exact support counts.

    """
    result = []

    def extend(prefix: int, suffix: list[tuple[int, int]]) -> None:
        for offset, (item, owners) in enumerate(suffix):
            combined = prefix | (1 << item)
            if combined.bit_count() >= 2:
                result.append((combined, owners.bit_count()))
            if combined.bit_count() >= maximum_size:
                continue
            following = []
            for next_item, next_owners in suffix[offset + 1 :]:
                intersection = owners & next_owners
                if intersection.bit_count() >= minimum_support:
                    following.append((next_item, intersection))
            if following:
                extend(combined, following)

    extend(
        0,
        [
            (item, owners)
            for item, owners in enumerate(columns)
            if owners.bit_count() >= minimum_support
        ],
    )
    return result


def select_packages(
    patterns: list[tuple[int, int]],
    columns: tuple[int, ...],
    transactions: int,
    catalog: Catalog,
    config: StructureConfig,
) -> tuple[int, ...]:
    candidates = []
    for mask, count in patterns:
        items = mask_indices(mask)
        if len(items) < 3 or any(catalog.ancestors[item] & mask for item in items):
            continue
        cost = sum(catalog.costs[item] for item in items)
        if cost > config.maximum_cost:
            continue
        expected = math.prod(columns[item].bit_count() / transactions for item in items)
        lift = count / transactions / max(expected, 1e-12)
        if lift > 1:
            candidates.append((count / transactions * math.log(lift), mask))
    candidates.sort(reverse=True)
    selected = []
    for _, mask in candidates:
        if all(inventory_distance(mask, previous) >= 0.35 for previous in selected):
            selected.append(mask)
        if len(selected) == config.package_limit:
            break
    return tuple(selected)


def community_proposals(
    columns: tuple[int, ...],
    transactions: int,
    minimum_support: int,
    *,
    resolution: float = 0.08,
    seed: int = 7,
) -> tuple[tuple[int, ...], dict[str, object]]:
    items = [
        item
        for item, owners in enumerate(columns)
        if owners.bit_count() >= minimum_support
    ]
    edges = []
    weights = []
    for first, item in enumerate(items):
        for second in range(first + 1, len(items)):
            other = items[second]
            support = (columns[item] & columns[other]).bit_count()
            if support < minimum_support:
                continue
            probability = support / transactions
            lift = (
                support
                * transactions
                / (columns[item].bit_count() * columns[other].bit_count())
            )
            if lift <= 1 or probability >= 1:
                continue
            weight = math.log(lift) / -math.log(probability) * support / (support + 100)
            edges.append((first, second))
            weights.append(weight)
    graph = igraph.Graph(n=len(items), edges=edges, directed=False)
    if not edges:
        return (), {"vertices": len(items), "edges": 0, "communities": 0}
    partition = leidenalg.find_partition(
        graph,
        leidenalg.CPMVertexPartition,
        weights=weights,
        resolution_parameter=resolution,
        seed=seed,
        n_iterations=-1,
    )
    communities = tuple(
        sorted(
            (
                sum(1 << items[index] for index in community)
                for community in partition
                if len(community) >= 2
            ),
            key=lambda mask: (-mask.bit_count(), mask),
        )
    )
    return communities, {
        "vertices": len(items),
        "edges": len(edges),
        "communities": len(communities),
        "quality": partition.quality(),
        "resolution": resolution,
        "seed": seed,
        "connected": all(
            graph.induced_subgraph(community).is_connected() for community in partition
        ),
    }


def include_components(themes: tuple[int, ...], catalog: Catalog) -> tuple[int, ...]:
    result = []
    for theme in themes:
        expanded = theme
        for item in mask_indices(theme):
            expanded |= catalog.ancestors[item]
        result.append(expanded)
    return tuple(result)


def prepare_structures(
    data: Path,
    catalog: Catalog,
    output: Path,
    config: StructureConfig | None = None,
) -> None:
    config = config or StructureConfig()
    total_started = time.perf_counter()
    statistics = json.loads(
        (data / "train/statistics.json").read_text(encoding="utf-8")
    )
    if statistics["partition"] != "train":
        raise ValueError("Structure proposals require training inventories")
    statistics = json.loads(
        (data / "train/statistics.json").read_text(encoding="utf-8")
    )
    results = {}
    for hero, _, _ in statistics["hero_counts"]:
        with np.load(data / "train" / f"{hero}-1201.npz") as values:
            matrix = values["matrix"]
            transactions = len(matrix)
            columns = tuple(
                bitset(matrix[:, item]) if catalog.costs[item] >= 1600 else 0
                for item in range(matrix.shape[1])
            )
        support = max(
            config.minimum_owners, math.ceil(transactions * config.support_fraction)
        )
        started = time.perf_counter()
        patterns = mine_itemsets(columns, support, config.maximum_size)
        packages = select_packages(patterns, columns, transactions, catalog, config)
        eclat_seconds = time.perf_counter() - started
        started = time.perf_counter()
        communities, details = community_proposals(
            columns,
            transactions,
            support,
            resolution=config.resolution,
            seed=config.seed,
        )
        leiden_seconds = time.perf_counter() - started
        results[str(hero)] = {
            "transactions": transactions,
            "minimum_support": support,
            "eclat": {
                "themes": [hex(mask) for mask in include_components(packages, catalog)],
                "packages": [hex(mask) for mask in packages],
                "frequent_itemsets": len(patterns),
                "seconds": eclat_seconds,
            },
            "leiden": {
                "themes": [
                    hex(mask) for mask in include_components(communities, catalog)
                ],
                "packages": [hex(mask) for mask in communities],
                "seconds": leiden_seconds,
                **details,
            },
        }
        sys.stdout.write(
            f"Prepared hero {hero}: {len(patterns)} itemsets, {len(communities)} communities\n"
        )
        sys.stdout.flush()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "data_fingerprint": statistics["fingerprint"],
                "patch": statistics["patch"],
                "config": asdict(config),
                "elapsed_seconds": time.perf_counter() - total_started,
                "heroes": results,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prepare ECLAT and Leiden beam proposals"
    )
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--data", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("generated/purchase-guide-search/structures.json"),
    )
    parser.add_argument("--resolution", type=float, default=0.08)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--minimum-owners", type=int, default=100)
    parser.add_argument("--support-fraction", type=float, default=0.01)
    parser.add_argument("--maximum-size", type=int, default=4)
    parser.add_argument("--package-limit", type=int, default=12)
    arguments = parser.parse_args()
    prepare_structures(
        arguments.data,
        load_catalog(arguments.source),
        arguments.output,
        StructureConfig(
            arguments.resolution,
            arguments.seed,
            arguments.minimum_owners,
            arguments.support_fraction,
            arguments.maximum_size,
            arguments.package_limit,
        ),
    )


if __name__ == "__main__":
    main()
