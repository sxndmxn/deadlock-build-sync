"""Observed core order and mechanics-required component expansion."""

from __future__ import annotations

from collections import Counter
from itertools import combinations
from typing import TYPE_CHECKING

import numpy as np
from deadlock_build_sync.mechanics import (
    InventoryState,
    ItemGraph,
    MechanicsError,
    purchase_item,
    schedule_component_path,
)
from deadlock_build_sync.offline.production_sequence import (
    _ranked_agreement_orders,  # ruff: ignore[import-private-name] -- Reuse the frozen repository baseline without changing production API.
)

from experiments.core_discovery.candidates import ownership
from experiments.core_discovery.patterns import prefixspan
from experiments.identity_paths.config import ORDER_MINIMUM, ORDER_SHARE

if TYPE_CHECKING:
    from experiments.core_discovery.data import HeroData


def core_times(data: HeroData, items: list[int], fold: str) -> np.ndarray:
    index = {item: column for column, item in enumerate(data.items)}
    columns = tuple(index[item] for item in items)
    matrix = data.matrix[data.mask(fold)]
    owners = ownership(matrix, columns)
    return data.times[data.mask(fold)][owners][:, columns]


def order_evidence(times: np.ndarray, items: list[int], order: list[int]) -> dict:
    positions = [items.index(item) for item in order]
    follows = np.all(np.diff(times[:, positions], axis=1) > 0, axis=1)
    count = int(follows.sum())
    share = count / max(1, len(times))
    return {
        "owners": len(times),
        "ordered_owners": count,
        "share": share,
        "passes": count >= ORDER_MINIMUM and share >= ORDER_SHARE,
    }


def expanded_path(order: list[int], graph: ItemGraph) -> list[dict]:
    priorities = {item: (float(index), 0.0, item) for index, item in enumerate(order)}
    path = schedule_component_path(graph, order, priorities)
    state, actions, spent = InventoryState(), [], 0
    for item in path:
        credit = graph.credited_component_value(item, state.owned)
        cash = graph.incremental_cash_cost(item, state.owned)
        state = purchase_item(graph, state, item)
        spent += cash
        actions.append({
            "item_id": item,
            "name": graph.require(item).name,
            "role": "core" if item in order else "required_component",
            "component_credit": credit,
            "incremental_cost": cash,
            "cumulative_cost": spent,
            "owned_after": list(state.owned),
        })
    if set(state.owned) != set(order) or spent != sum(
        graph.require(item).cost for item in order
    ):
        raise MechanicsError("Path final inventory or component accounting disagrees")
    return actions


def ranked_orders(
    times: np.ndarray, items: list[int], method: str
) -> list[tuple[int, list[int]]]:
    if method == "prefixspan":
        patterns = prefixspan(times, minimum=ORDER_MINIMUM, length=len(items))
        return sorted(
            (
                (count, [items[column] for column in order])
                for order, count in patterns.items()
            ),
            key=lambda row: (-row[0], row[1]),
        )
    if method != "pairwise":
        raise ValueError(f"Unknown order method: {method}")
    precedence = Counter()
    for first, second in combinations(range(len(items)), 2):
        precedence[items[first], items[second]] = int(
            (times[:, first] < times[:, second]).sum()
        )
        precedence[items[second], items[first]] = int(
            (times[:, second] < times[:, first]).sum()
        )
    return [
        (score, list(order))
        for score, order in _ranked_agreement_orders(tuple(items), precedence)
    ]


def choose_order(
    data: HeroData, items: list[int], method: str, graph: ItemGraph
) -> dict:
    times = core_times(data, items, "discovery")
    ranked = ranked_orders(times, items, method)
    illegal = 0
    for score, order in ranked:
        try:
            actions = expanded_path(order, graph)
        except MechanicsError:
            illegal += 1
            continue
        discovery = order_evidence(times, items, order)
        selection = order_evidence(core_times(data, items, "selection"), items, order)
        return {
            "method": method,
            "order": order,
            "ranking_score": score,
            "discovery": discovery,
            "selection": selection,
            "admitted_before_validation": discovery["passes"] and selection["passes"],
            "legal": True,
            "actions": actions,
            "illegal_orders_skipped": illegal,
            "reason": None
            if discovery["passes"] and selection["passes"]
            else "Full order lacks discovery/selection support",
        }
    return {
        "method": method,
        "order": [],
        "actions": [],
        "legal": False,
        "admitted_before_validation": False,
        "illegal_orders_skipped": illegal,
        "reason": "No observed full order"
        if not ranked
        else "No mechanically legal order",
    }
