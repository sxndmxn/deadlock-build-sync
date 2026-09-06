"""Shared three-item contract for five automatic core discovery methods."""

from __future__ import annotations

import math

import numpy as np

from tools.comparisons.core_discovery.latent import bernoulli, leiden, nmf
from tools.comparisons.core_discovery.patterns import eclat, prefixspan

METHODS = ("eclat", "prefixspan", "nmf", "bernoulli", "leiden")
SEEDS = (42, 43, 44)


def valid_core(items: tuple[int, ...], catalog: dict) -> bool:
    if len(items) != 3 or len(set(items)) != 3:
        return False
    assets = [catalog[str(item)] for item in items]
    if (
        min(asset["cost"] for asset in assets) < 1600
        or sum(asset["cost"] for asset in assets) > 12800
    ):
        return False
    return not any(set(items) & set(asset["ancestors"]) for asset in assets)


def ownership(matrix: np.ndarray, core: tuple[int, ...]) -> np.ndarray:
    return matrix[:, core].all(axis=1)


def joint_lift(matrix: np.ndarray, core: tuple[int, ...], count: int) -> float:
    expected = float(matrix[:, core].mean(axis=0).prod())
    return count / len(matrix) / expected if expected > 0 else 0.0


def rank_proposals(
    matrix: np.ndarray,
    item_ids: tuple[int, ...],
    catalog: dict,
    proposals: dict,
    limit: int = 20,
) -> list[dict]:
    ranked = []
    for columns, details in proposals.items():
        items = tuple(item_ids[column] for column in columns)
        if not valid_core(items, catalog):
            continue
        count = int(ownership(matrix, columns).sum())
        lift = joint_lift(matrix, columns, count)
        if count < 100 or lift < 1.1:
            continue
        support = details.get("ordered_support", count)
        ranked.append({
            "items": list(items),
            "names": [catalog[str(item)]["name"] for item in items],
            "cost": sum(catalog[str(item)]["cost"] for item in items),
            "discovery_support": count,
            "discovery_lift": lift,
            "score": support / len(matrix) * math.log(lift),
            "order": [item_ids[column] for column in details.get("order", ())],
            "ordered_support": details.get("ordered_support"),
        })
    return sorted(ranked, key=lambda row: (-row["score"], row["items"]))[:limit]


def propose(
    method: str, matrix: np.ndarray, times: np.ndarray, seed: int
) -> tuple[dict, dict]:
    if method == "eclat":
        patterns = eclat(matrix)
        return {core: {} for core in patterns}, {
            "frequent_triples": len(patterns),
            "deterministic": True,
        }
    if method == "prefixspan":
        patterns = prefixspan(times)
        proposed = {}
        for order, count in sorted(
            patterns.items(), key=lambda pair: (-pair[1], pair[0])
        ):
            proposed.setdefault(
                tuple(sorted(order)), {"order": order, "ordered_support": count}
            )
        return proposed, {"ordered_patterns": len(patterns), "deterministic": True}
    methods = {"nmf": nmf, "bernoulli": bernoulli, "leiden": leiden}
    if method not in methods:
        raise ValueError(f"Unknown discovery algorithm: {method}")
    triples, diagnostic = methods[method](matrix, seed)
    return {core: {} for core in sorted(triples)}, diagnostic


def discover(
    method: str,
    matrix: np.ndarray,
    times: np.ndarray,
    item_ids: tuple[int, ...],
    catalog: dict,
    seed: int,
) -> tuple[list[dict], dict]:
    if not np.array_equal(matrix, times >= 0) or (times >= 1200).any():
        raise ValueError("Inventory and strictly pre-landmark acquisitions disagree")
    proposals, diagnostic = propose(method, matrix, times, seed)
    ranked = rank_proposals(matrix, item_ids, catalog, proposals)
    return ranked, {"proposed_triples": len(proposals), **diagnostic}
