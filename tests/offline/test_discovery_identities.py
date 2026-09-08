"""Production regressions moved from the frozen identity experiment."""

from __future__ import annotations

from dataclasses import replace
from itertools import combinations
from typing import TYPE_CHECKING

import numpy as np
import pytest

from deadlock_build_sync.mechanics import ItemGraph, ItemNode, MechanicsError
from deadlock_build_sync.offline.discovery_data import HeroData
from deadlock_build_sync.offline.discovery_fit import discover_hero, select
from deadlock_build_sync.offline.discovery_grouping import consolidate, merge_complete
from deadlock_build_sync.offline.discovery_mining import mine, parent_for, valid_items
from deadlock_build_sync.offline.discovery_orders import (
    expanded_path,
    order_evidence,
    ranked_orders,
)
from deadlock_build_sync.offline.discovery_tactics import explain
from deadlock_build_sync.value_validation import (
    integer,
    require_object_list,
    require_object_rows,
)

if TYPE_CHECKING:
    from deadlock_build_sync.offline.discovery_types import Candidate, Catalog


def graph_fixture(count: int = 12, *, active: bool = False) -> ItemGraph:
    return ItemGraph({
        item: ItemNode(
            item,
            f"item{item}",
            f"Item {item}",
            1600,
            "weapon",
            2,
            (),
            active=active,
            unique=True,
            max_count=1,
        )
        for item in range(count)
    })


def catalog_fixture(count: int) -> Catalog:
    return {
        str(item): {"cost": 1600, "name": f"Item {item}", "ancestors": []}
        for item in range(count)
    }


def planted_data(seed: int = 17, per_fold: int = 1200) -> HeroData:
    rng = np.random.default_rng(seed)
    size = per_fold * 3
    group = np.tile(np.arange(per_fold) % 3, 3)
    matrix = np.zeros((size, 13), dtype=bool)
    for identity in range(3):
        matrix[group == identity, identity * 4 : identity * 4 + 4] = True
    matrix[:, 12] = rng.random(size) < 0.65
    times = np.where(matrix, 100 + 55 * np.arange(13)[None, :], -1).astype(np.int32)
    won = rng.random(size) < np.asarray([0.75, 0.65, 0.25])[group]
    return HeroData(
        6,
        tuple(range(13)),
        matrix,
        times,
        np.arange(size),
        np.repeat(["discovery", "selection", "validation"], per_fold),
        won,
        np.full(size, 15000.0),
        np.zeros(size),
        np.full(size, 90),
        np.ones(size),
        np.zeros((size, 6), dtype=int),
    )


def test_mining_recovers_actual_cores_and_never_unobserved_union() -> None:
    data = planted_data()
    rows = data.mask("discovery")
    result = mine(data.matrix[rows], data.times[rows], data.items, catalog_fixture(13))
    candidates = {tuple(row["items"]): row for row in result["candidates"]}
    assert (0, 1, 2, 3) in candidates
    assert (4, 5, 6, 7) in candidates
    for items, row in candidates.items():
        assert (
            int(data.matrix[rows][:, items].all(axis=1).sum())
            == row["discovery_support"]
        )
        assert (
            set(items) - {12} <= set(range(4))
            or set(items) - {12} <= set(range(4, 8))
            or set(items) - {12} <= set(range(8, 12))
        )


def test_parent_retention_and_cost_upgrade_contract() -> None:
    assert parent_for((0, 1, 2, 3), 100, {(0, 1, 2): 201}) is None
    assert parent_for((0, 1, 2, 3), 100, {(0, 1, 2): 200}) == (0, 1, 2)
    catalog = catalog_fixture(6)
    assert valid_items((0, 1, 2, 3), catalog)
    catalog["3"]["ancestors"] = [2]
    assert not valid_items((0, 1, 2, 3), catalog)
    catalog["3"]["ancestors"] = []
    catalog["3"]["cost"] = 16000
    assert not valid_items((0, 1, 2, 3), catalog)


def test_complete_link_stops_transitive_chain_and_keeps_isolate() -> None:
    weights = np.eye(4)
    weights[0, 1] = weights[1, 0] = 0.9
    weights[1, 2] = weights[2, 1] = 0.8
    groups = merge_complete(weights, weights > 0)
    assert groups == [[0, 1], [2], [3]]
    for group in groups:
        assert all(
            weights[first, second] > 0 for first, second in combinations(group, 2)
        )


def test_leiden_merges_variants_and_retains_distinct_identities() -> None:
    matrix = np.zeros((300, 9), dtype=bool)
    matrix[:150, :5] = True
    matrix[150:, 5:] = True
    candidates: list[Candidate] = [
        {"items": [0, 1, 2, 3]},
        {"items": [0, 1, 2, 4]},
        {"items": [5, 6, 7, 8]},
    ]
    result = consolidate(candidates, matrix, tuple(range(9)))
    assert result["groups"] == [[0, 1], [2]]
    assert len(result["seeds"]) == 3


def test_pairwise_ranking_does_not_bypass_full_order_support() -> None:
    times = np.asarray(
        [[10, 20, 30, 40]] * 30 + [[20, 30, 10, 40]] * 30 + [[30, 10, 20, 40]] * 30
    )
    ranked = ranked_orders(times, [0, 1, 2, 3], "pairwise")
    assert len(ranked) == 24
    evidence = order_evidence(times, [0, 1, 2, 3], ranked[0][1])
    assert evidence["ordered_owners"] <= 30


def test_component_rebuy_credit_and_active_inventory_limits() -> None:
    graph = graph_fixture()
    graph.nodes[1] = replace(graph.nodes[1], cost=3200, component_classes=("item0",))
    graph.nodes[2] = replace(graph.nodes[2], cost=3200, component_classes=("item0",))
    graph = ItemGraph(graph.nodes)
    actions = expanded_path([1, 2, 3, 4], graph)
    assert sum(action["item_id"] == 0 for action in actions) == 2
    assert sum(integer(action["incremental_cost"]) for action in actions) == 9600
    assert set(require_object_list(actions[-1]["owned_after"])) == {1, 2, 3, 4}
    with pytest.raises(MechanicsError):
        expanded_path([0, 1, 2, 3, 4], graph_fixture(active=True))
    with pytest.raises(MechanicsError):
        expanded_path(list(range(12)), graph_fixture())


def test_selection_keeps_losing_core_and_ignores_validation_outcomes() -> None:
    data = planted_data()
    original = discover_hero(data, catalog_fixture(13))
    flipped = data.won.copy()
    flipped[data.mask("validation")] = ~flipped[data.mask("validation")]
    changed = discover_hero(replace(data, won=flipped), catalog_fixture(13))
    assert original["candidates"] == changed["candidates"]
    assert original["selected"] == changed["selected"]
    for indices in original["selected"].values():
        assert indices
        assert any(
            {8, 9, 10, 11} <= set(original["candidates"][index]["items"])
            for index in indices
        )


def test_group_selection_returns_existing_representatives_only() -> None:
    candidates: list[Candidate] = [
        {
            "items": [0, 1, 2, item],
            "selection_rejections": [],
            "selection": {"owners": 100, "adjusted": {"lower_95": score}},
        }
        for item, score in ((3, 0.04), (4, 0.02), (5, 0.03))
    ]
    assert select(candidates) == [0, 2, 1]


def test_tactical_explanation_requires_two_items_and_kit_source() -> None:
    assets: list[dict[str, object]] = [
        {
            "id": 10,
            "class_name": "ability",
            "name": "Ability",
            "description": "Heavy melee damage",
        }
    ]
    assets += [
        {
            "id": item,
            "name": f"Item {item}",
            "description": "Heavy melee damage" if item < 2 else "Move speed",
        }
        for item in range(4)
    ]
    hero: dict[str, object] = {"items": {"signature1": "ability"}}
    result = explain(hero, [0, 1, 2, 3], assets)
    assert result["supported_focus"]
    assert (
        require_object_rows(result["focuses"][0]["abilities"])[0]["ref"]
        == "asset:item:10:description"
    )
    assert not explain(hero, [1, 2, 3], assets)["supported_focus"]
