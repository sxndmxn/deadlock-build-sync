"""Calculate item pools and purchase positions from core ownership records."""

from __future__ import annotations

from collections import defaultdict

import numpy as np

from deadlock_build_sync.value_validation import integer, require_object_list

from .discovery_types import (
    FirstPurchaseRow,
    ItemPoolEvidence,
    ItemPoolStatistics,
    PurchasePlacementEvidence,
)
from .production_timing import _count_item_purchase_intervals

MINIMUM_POOL_BUYERS = 20


def summarize_purchase_evidence(
    rows: list[FirstPurchaseRow], population: int
) -> ItemPoolEvidence:
    times, wealths, histories = defaultdict(list), defaultdict(list), {}
    for match, slot, raw_item, bought, wealth, observed in rows:
        actor = (int(match), int(slot))
        item = int(raw_item)
        if item in histories.setdefault(actor, {}):
            raise ValueError("First-purchase evidence contains a duplicate player/item")
        histories[actor][item] = float(bought)
        times[item].append(float(bought))
        if wealth is not None and observed is not None and 0 < bought - observed <= 300:
            wealths[item].append(float(wealth))
    if len(histories) > population:
        raise ValueError("Purchase evidence exceeds the discovered-owner population")
    stats: dict[int, ItemPoolStatistics] = {
        item: {
            "buyers": len(values),
            "adoption": len(values) / max(1, population),
            "time_seconds_q25_q50_q75": calculate_purchase_quantiles(values) or [],
            "fresh_wealth_observations": len(wealths[item]),
            "net_worth_q25_q50_q75": calculate_purchase_quantiles(wealths[item]),
        }
        for item, values in times.items()
    }
    return {"population": population, "items": stats, "histories": histories}


def calculate_purchase_timing_policy(
    stats: dict[int, ItemPoolStatistics],
) -> tuple[dict[int, tuple[float, float, int]], dict[int, tuple[float, float]]]:
    priorities, bounds = {}, {}
    for item, evidence in stats.items():
        wealth = evidence["net_worth_q25_q50_q75"]
        reliable = (
            wealth is not None
            and evidence["fresh_wealth_observations"] >= MINIMUM_POOL_BUYERS
            and evidence["fresh_wealth_observations"] / evidence["buyers"] >= 0.5
        )
        time = evidence["time_seconds_q25_q50_q75"][1]
        priorities[item] = (wealth[1] if reliable else float("inf"), time, item)
        if reliable:
            bounds[item] = (wealth[0], wealth[2])
    return priorities, bounds


def estimate_purchase_placement(
    item: int, path: list[int], evidence: ItemPoolEvidence
) -> PurchasePlacementEvidence:
    """Count purchases between adjacent core purchases with known, distinct times.

    Returns:
        A supported checkpoint or unknown timing.

    """
    counted = _count_item_purchase_intervals(item, tuple(path), evidence["histories"])
    counts = [
        integer(value) for value in require_object_list(counted["counts_by_checkpoint"])
    ]
    buyers = evidence["items"][item]["buyers"]
    anchor = int(np.argmax(counts))
    supported = (
        bool(path)
        and counts[anchor] >= MINIMUM_POOL_BUYERS
        and counts[anchor] / buyers >= 0.1
    )
    return {
        "after_step": anchor if supported else None,
        "observed_after_step": anchor,
        "support": counts[anchor],
        "buyers": buyers,
        "supported": supported,
        "counts_by_checkpoint": counts,
        "basis": "observed adjacent first-purchase anchors"
        if supported
        else "Timing unknown; adjacent purchase evidence is insufficient",
    }


def calculate_purchase_quantiles(values: list[float]) -> list[float] | None:
    return np.quantile(values, [0.25, 0.50, 0.75]).tolist() if values else None
