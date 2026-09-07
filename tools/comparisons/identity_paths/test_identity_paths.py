"""Regression checks for identities, complete orders and purchase mechanics."""

from __future__ import annotations

import json
from dataclasses import replace
from itertools import combinations, permutations
from typing import TYPE_CHECKING

import numpy as np
import pytest
from deadlock_build_sync.mechanics import ItemGraph, ItemNode, MechanicsError
from deadlock_build_sync.offline.config import sha256_json

from tools.comparisons.core_discovery.data import HeroData
from tools.comparisons.identity_paths.fit import discover_hero, select
from tools.comparisons.identity_paths.grouping import consolidate, merge_complete
from tools.comparisons.identity_paths.mining import mine, parent_for, valid_items
from tools.comparisons.identity_paths.orders import (
    expanded_path,
    order_evidence,
    ranked_orders,
)
from tools.comparisons.identity_paths.purchase_data import action_window
from tools.comparisons.identity_paths.storage import (
    producer_hashes,
    verify_original_assets,
    verify_run,
)
from tools.comparisons.identity_paths.tactics import explain
from tools.comparisons.qdfm.state import Catalog, Purchase

if TYPE_CHECKING:
    from pathlib import Path


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


def catalog_fixture(count: int) -> dict:
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
    candidates = [
        {"items": [0, 1, 2, 3]},
        {"items": [0, 1, 2, 4]},
        {"items": [5, 6, 7, 8]},
    ]
    result = consolidate(candidates, matrix, tuple(range(9)))
    assert result["groups"] == [[0, 1], [2]]
    assert len(result["seeds"]) == 3


def test_full_prefixspan_support_matches_brute_force_with_ties() -> None:
    times = np.asarray(
        [[10, 20, 30, 40]] * 30 + [[20, 10, 30, 40]] * 25 + [[10, 10, 30, 40]] * 40
    )
    actual = {
        tuple(order): count
        for count, order in ranked_orders(times, [0, 1, 2, 3], "prefixspan")
    }
    expected = {}
    for order in permutations(range(4)):
        count = int((np.diff(times[:, order], axis=1) > 0).all(axis=1).sum())
        if count >= 20:
            expected[order] = count
    assert actual == expected == {(0, 1, 2, 3): 30, (1, 0, 2, 3): 25}
    assert not order_evidence(
        np.asarray([[10, 10, 20, 30]] * 100), [0, 1, 2, 3], [0, 1, 2, 3]
    )["passes"]


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
    assert sum(action["incremental_cost"] for action in actions) == 9600
    assert set(actions[-1]["owned_after"]) == {1, 2, 3, 4}
    with pytest.raises(MechanicsError):
        expanded_path([0, 1, 2, 3, 4], graph_fixture(active=True))
    with pytest.raises(MechanicsError):
        expanded_path(list(range(12)), graph_fixture())


def test_sale_upgrade_rebuy_inventory_and_latest_purchase_window() -> None:
    catalog = object.__new__(Catalog)
    catalog.ancestors = {0: frozenset(), 1: frozenset({0}), 2: frozenset()}
    purchases = [
        Purchase(0, 10, 0),
        Purchase(1, 20, 50),
        Purchase(0, 30, 0),
        Purchase(2, 40, 45),
        Purchase(1, 60, 0),
    ]
    assert catalog.inventory(purchases, 55) == (0,)
    assert catalog.inventory(purchases, 65) == (1,)
    events = {
        7: {
            "items": {1: [(20, 50, 3000, 10), (60, 0, 6000, 55), (1200, 0, 9000, 1190)]}
        }
    }
    result = action_window(events, np.asarray([7]), np.asarray([70]), 1)
    assert result["time_seconds_q25_q50_q75"] == [60, 60, 60]
    assert result["net_worth_q25_q50_q75"] == [6000, 6000, 6000]


def test_selection_keeps_supported_losing_core_and_ignores_validation() -> None:
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


def test_selection_orders_all_candidates_before_legal_group_admission() -> None:
    candidates = [
        {
            "items": [0, 1, 2, item],
            "selection_rejections": [],
            "selection": {"owners": 100, "adjusted": {"lower_95": score}},
        }
        for item, score in ((3, 0.04), (4, 0.02), (5, 0.03))
    ]
    assert select(candidates) == [0, 2, 1]


def test_tactical_explanation_requires_two_items_and_kit_source() -> None:
    assets = [
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
    hero = {"items": {"signature1": "ability"}}
    result = explain(hero, [0, 1, 2, 3], assets)
    assert result["supported_focus"]
    assert result["focuses"][0]["abilities"][0]["ref"] == "asset:item:10:description"
    assert not explain(hero, [1, 2, 3], assets)["supported_focus"]


def test_frozen_source_change_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_text(
        json.dumps({"producer_sha256": {}}), encoding="utf-8"
    )
    assert producer_hashes()["identity_paths"]
    with pytest.raises(ValueError, match="sources changed"):
        verify_run(tmp_path)


def test_original_asset_hashes_use_source_canonical_json(tmp_path: Path) -> None:
    (tmp_path / "raw").mkdir()
    content = [{"id": 1, "cost": 1600}]
    recorded = {}
    for name in ("items.json", "items-all.json", "heroes.json"):
        (tmp_path / "raw" / name).write_text(
            json.dumps(content, indent=2), encoding="utf-8"
        )
        recorded[name] = sha256_json(content)
    verify_original_assets(tmp_path, recorded)
    (tmp_path / "raw/items.json").write_text('[{"id":1,"cost":3200}]', encoding="utf-8")
    with pytest.raises(ValueError, match="Original asset changed"):
        verify_original_assets(tmp_path, recorded)
