"""Leiden consensus followed by deterministic complete-link consolidation."""

from __future__ import annotations

from itertools import combinations

import igraph
import leidenalg
import numpy as np

from experiments.core_discovery.candidates import ownership
from experiments.identity_paths.config import GROUP_JACCARD, SEEDS


def similarities(
    candidates: list[dict], matrix: np.ndarray, items: tuple
) -> np.ndarray:
    index = {item: column for column, item in enumerate(items)}
    masks = [
        ownership(matrix, tuple(index[item] for item in candidate["items"]))
        for candidate in candidates
    ]
    result = np.eye(len(candidates))
    for first, second in combinations(range(len(candidates)), 2):
        common = set(candidates[first]["items"]) & set(candidates[second]["items"])
        if len(common) < 2:
            continue
        jaccard = (masks[first] & masks[second]).sum() / max(
            1, int((masks[first] | masks[second]).sum())
        )
        if jaccard >= GROUP_JACCARD:
            result[first, second] = result[second, first] = jaccard
    return result


def merge_complete(weights: np.ndarray, eligible: np.ndarray) -> list[list[int]]:
    groups = [(index,) for index in range(len(weights))]
    while True:
        choices = []
        for first, second in combinations(range(len(groups)), 2):
            block = np.ix_(groups[first], groups[second])
            if eligible[block].all():
                merged = tuple(sorted((*groups[first], *groups[second])))
                choices.append((-float(weights[block].mean()), merged, first, second))
        if not choices:
            return [list(group) for group in sorted(groups)]
        _, merged, first, second = min(choices)
        groups = [
            group for index, group in enumerate(groups) if index not in {first, second}
        ]
        groups.append(merged)
        groups.sort()


def consolidate(candidates: list[dict], matrix: np.ndarray, items: tuple) -> dict:
    weights = similarities(candidates, matrix, items)
    first, second = np.nonzero(np.triu(weights > 0, 1))
    graph = igraph.Graph(
        n=len(candidates), edges=list(zip(first.tolist(), second.tolist(), strict=True))
    )
    assignments = []
    for seed in SEEDS:
        if not len(first):
            membership = list(range(len(candidates)))
        else:
            partition = leidenalg.find_partition(
                graph,
                leidenalg.RBConfigurationVertexPartition,
                weights=weights[first, second].tolist(),
                resolution_parameter=1,
                n_iterations=10,
                seed=seed,
            )
            membership = list(partition.membership)
        assignments.append({"seed": seed, "membership": membership})
    votes = np.zeros_like(weights, dtype=int)
    for assignment in assignments:
        labels = np.asarray(assignment["membership"])
        votes += labels[:, None] == labels[None, :]
    groups = merge_complete(weights, (weights > 0) & (votes >= 2))
    return {
        "groups": groups,
        "seeds": assignments,
        "edges": [
            {
                "first": int(left),
                "second": int(right),
                "jaccard": float(weights[left, right]),
                "votes": int(votes[left, right]),
            }
            for left, right in zip(first, second, strict=True)
        ],
        "candidate_order": [row["items"] for row in candidates],
    }
