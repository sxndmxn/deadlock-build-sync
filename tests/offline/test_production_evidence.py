from collections import Counter
from itertools import combinations
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch

import duckdb
import polars as pl
import pytest

from deadlock_build_sync.mechanics import ItemGraph
from deadlock_build_sync.offline.build_paths import DiscoveredBuildPath
from deadlock_build_sync.offline.config import RunPaths
from deadlock_build_sync.offline.core_policy import (
    BackboneSelection,
    _bundle_support_by_size_and_fold,
    complete_default_core,
    cross_fitted_dr_contrast,
    select_supported_backbone,
)
from deadlock_build_sync.offline.production_evidence import (
    UnsupportedBuildPathError,
    _core_economy_reference,
    _core_target_order,
    _expanded_default_path,
    _item_payload,
    _maximum_agreement_orders,
    _parallel_hero_export,
    _patch_content_sha256,
    _path_cohort_summary,
    _path_payloads,
    _sequence_rows,
    _situational_policy,
    _situational_selection_matchups,
    _tier_policy,
)


def _item_metric_row() -> dict[str, object]:
    return {
        "item_id": 101,
        "item_name": "Compress Cooldown",
        "tier": 3,
        "cost": 3200,
        "slot": "spirit",
        "active": False,
        "adopter_matches": 100,
        "selection_adopter_matches": 100,
        "training_adopter_matches": 50,
        "validation_adopter_matches": 50,
        "test_adopter_matches": 0,
        "hero_player_matches": 200,
        "purchase_events": 105,
        "wins": 55,
        "adoption_rate": 0.5,
        "raw_outcome_rate": 0.55,
        "median_buy_time_s": 900.0,
        "median_valid_buy_net_worth": 12_000.0,
        "buy_nw_q25": 10_000.0,
        "buy_nw_q75": 14_000.0,
        "valid_buy_nw_share": 0.95,
        "selection_median_buy_time_s": 900.0,
        "selection_median_valid_buy_net_worth": 12_000.0,
        "selection_buy_nw_q25": 10_000.0,
        "selection_buy_nw_q75": 14_000.0,
        "selection_valid_buy_nw_observations": 100,
        "training_valid_buy_nw_observations": 50,
        "validation_valid_buy_nw_observations": 50,
        "training_buy_nw_q25": 10_000.0,
        "training_buy_nw_q75": 14_000.0,
        "validation_buy_nw_q25": 10_000.0,
        "validation_buy_nw_q75": 14_000.0,
        "imbued_ability_id": 40,
        "target_matches": 75,
        "imbue_observations": 100,
        "target_share": 0.75,
    }


def test_situational_matchups_keep_full_64_bit_item_ids_after_early_rows() -> None:
    item_ids = [
        item_id
        for enemy_id in range(1, 53)
        for item_id in (
            (100 + enemy_id * 2, 101 + enemy_id * 2)
            if enemy_id < 52
            else (2_717_651_715, 2_717_651_716)
        )
    ]
    cells = pl.DataFrame(
        {
            "scope": ["same_lane"] * len(item_ids),
            "hero_id": [6] * len(item_ids),
            "enemy_hero_id": [enemy_id for enemy_id in range(1, 53) for _ in range(2)],
            "phase": [1] * len(item_ids),
            "tier": [2] * len(item_ids),
            "item_id": item_ids,
            "observations": [40] * len(item_ids),
            "outcome_rate": [0.6, 0.5] * 52,
        },
        schema_overrides={"item_id": pl.Int64},
    )

    matchups = _situational_selection_matchups(cells)

    assert matchups["comparator_item_id"].dtype == pl.Int64
    assert 2_717_651_716 in matchups["comparator_item_id"].to_list()


def test_item_payload_admits_only_supported_majority_imbue_target() -> None:
    assets = {40: {"id": 40, "name": "Frozen Shelter"}}
    fold_eligible = {"train": 100, "validation": 100, "test": 0}

    supported = _item_payload(_item_metric_row(), assets, fold_eligible)
    weak = _item_payload(
        {**_item_metric_row(), "target_matches": 49, "target_share": 0.49},
        assets,
        fold_eligible,
    )

    assert supported["imbue_target_ability_id"] == 40
    assert supported["imbue_target_ability"] == "Frozen Shelter"
    assert supported["imbue_target_matches"] == 75
    assert supported["imbue_target_share"] == 0.75
    assert weak["imbue_target_ability_id"] is None
    assert weak["imbue_observations"] == 0


def test_hero_export_runs_eight_workers_and_preserves_order() -> None:
    jobs = [(index, {"id": index}) for index in range(1, 11)]
    expected = [{"hero_id": index} for index in range(1, 11)]

    with (
        patch(
            "deadlock_build_sync.offline.production_evidence.parallel_config"
        ) as config,
        patch("deadlock_build_sync.offline.production_evidence.Parallel") as parallel,
    ):
        parallel.return_value.return_value = expected
        result = _parallel_hero_export(
            jobs,
            lambda job: {"hero_id": job[1]["id"]},
        )

    config.assert_called_once_with(
        backend="loky",
        n_jobs=8,
        inner_max_num_threads=1,
    )
    parallel.assert_called_once_with()
    assert [row["hero_id"] for row in result] == list(range(1, 11))


def test_batched_backbone_counts_match_per_inventory_counting() -> None:
    inventories = {
        (1, 0): (1, 2, 3, 4, 5, 6),
        (2, 0): (1, 2, 3, 4, 5),
        (3, 0): (1, 2, 3, 4),
        (4, 0): (1, 2, 3, 4, 4),
    }
    folds = {1: "train", 2: "validation", 3: "test", 4: "train"}

    batched = _bundle_support_by_size_and_fold(
        inventories,
        folds,
        frozenset({6}),
    )

    for size in (4, 5, 6):
        expected = {fold: Counter() for fold in ("train", "validation", "test")}
        for (match_id, _), inventory in inventories.items():
            distinct = tuple(sorted(set(inventory) - {6}))
            if len(distinct) >= size:
                expected[folds[match_id]].update(combinations(distinct, size))
        assert batched[size] == expected


def test_path_export_retains_valid_sibling_when_one_path_abstains() -> None:
    bad = DiscoveredBuildPath(
        "bad",
        frozenset({(1, 0)}),
        (101,),
        {"train": 1},
        {},
    )
    good = DiscoveredBuildPath(
        "good",
        frozenset({(2, 0)}),
        (102,),
        {"train": 1},
        {},
    )
    context = cast(
        "Any",
        SimpleNamespace(
            mechanics_assets_by_id={},
            folds_by_match={1: "train", 2: "train"},
        ),
    )

    def build_payload(*args: object, **kwargs: object) -> dict[str, str]:
        del kwargs
        path = cast("DiscoveredBuildPath", args[3])
        if path.path_id == "bad":
            raise UnsupportedBuildPathError("unsupported tier")
        return {"path_id": path.path_id}

    con = duckdb.connect()
    try:
        with (
            patch(
                "deadlock_build_sync.offline.production_evidence._path_label",
                side_effect=["Bad", "Good"],
            ),
            patch(
                "deadlock_build_sync.offline.production_evidence._build_path_payload",
                side_effect=build_payload,
            ),
        ):
            payloads, abstentions = _path_payloads(
                con,
                12,
                {"id": 12},
                (bad, good),
                {(1, 0): (101,), (2, 0): (102,)},
                context,
            )
    finally:
        con.close()

    assert payloads == [{"path_id": "good"}]
    assert abstentions == [{"path_id": "bad", "reason": "unsupported tier"}]


def test_core_budget_summaries_ignore_test_rows() -> None:
    con = duckdb.connect()
    try:
        con.execute(
            """
            CREATE TABLE player_matches(
                match_id INTEGER,
                player_slot INTEGER,
                duration_s INTEGER,
                final_net_worth INTEGER,
                average_badge INTEGER
            )
            """
        )
        con.execute(
            "INSERT INTO player_matches VALUES "
            "(1, 0, 1000, 10000, 90), "
            "(2, 0, 2000, 20000, 90), "
            "(3, 0, 9999, 1000000, 90)"
        )
        con.execute("CREATE TABLE match_folds(match_id INTEGER, fold VARCHAR)")
        con.execute(
            "INSERT INTO match_folds VALUES "
            "(1, 'train'), (2, 'validation'), (3, 'test')"
        )
        con.execute(
            """
            CREATE TABLE purchases(
                match_id INTEGER,
                player_slot INTEGER,
                average_badge INTEGER,
                sold_time INTEGER,
                cost INTEGER
            )
            """
        )
        con.execute(
            """
            INSERT INTO purchases
            SELECT match_id, 0, 90, 0,
                   CASE WHEN match_id = 3 THEN 100000 ELSE 1000 END
            FROM range(1, 4) matches(match_id), range(4)
            """
        )

        cohort = _path_cohort_summary(
            con,
            frozenset({(1, 0), (2, 0), (3, 0)}),
        )
        reference = _core_economy_reference(
            con,
            {"minimum_badge": 71, "maximum_badge": 115},
        )
    finally:
        con.close()

    assert cohort == (3, 15_000)
    assert reference["matches"] == 2
    assert reference["player_matches"] == 2
    assert reference["median_final_net_worth"] == 15_000
    assert reference["median_final_inventory_cost"] == 4_000


def test_supported_backbone_uses_support_before_mechanic_affinity() -> None:
    item_ids = range(1, 17)
    graph = ItemGraph.from_assets([
        {
            "id": item_id,
            "class_name": f"item_{item_id}",
            "name": f"Item {item_id}",
            "cost": 1,
            "item_tier": 3,
            "item_slot_type": "weapon",
            "component_items": [],
            "shopable": True,
            "disabled": False,
            "is_active_item": False,
            "is_unique": True,
        }
        for item_id in item_ids
    ])
    inventories: dict[tuple[int, int], tuple[int, ...]] = {}
    folds: dict[int, str] = {}
    match_id = 1
    groups = (
        (34, (1, 2, 3, 4, 5, 6, 7, 8)),
        (33, (1, 2, 3, 4, 5, 9, 10, 11)),
        (33, (1, 2, 3, 4, 5, 12, 13, 14)),
        (120, (9, 10, 11, 12, 13, 14, 15, 16)),
    )
    for per_fold, inventory in groups:
        for fold in ("train", "validation", "test"):
            for _ in range(per_fold):
                inventories[match_id, 0] = inventory
                folds[match_id] = fold
                match_id += 1

    backbone = select_supported_backbone(
        inventories,
        folds,
        graph,
        mechanic_affinity=dict.fromkeys(range(1, 6), 3),
    )
    default, _, _ = complete_default_core(
        backbone,
        inventories,
        folds,
        graph,
        dict.fromkeys(graph.nodes, 1),
        20,
    )

    nucleus = set(range(9, 15))
    assert set(backbone.item_ids) == nucleus
    assert len(backbone.item_ids) == 6
    assert nucleus <= set(default)


def test_default_completion_uses_supported_candidates_near_economy_target() -> None:
    costs = {**dict.fromkeys(range(1, 9), 1), 9: 6, 10: 6}
    graph = ItemGraph.from_assets([
        {
            "id": item_id,
            "class_name": f"item_{item_id}",
            "name": f"Item {item_id}",
            "cost": cost,
            "item_tier": 3,
            "item_slot_type": "weapon",
            "component_items": [],
            "shopable": True,
            "disabled": False,
            "is_active_item": False,
            "is_unique": True,
        }
        for item_id, cost in costs.items()
    ])
    inventories: dict[tuple[int, int], tuple[int, ...]] = {}
    folds: dict[int, str] = {}
    match_id = 1
    for fold, cheap_count, target_count in (
        ("train", 30, 20),
        ("validation", 30, 20),
        ("test", 30, 20),
    ):
        for inventory, count in (
            ((*range(1, 7), 7, 8), cheap_count),
            ((*range(1, 7), 9, 10), target_count),
        ):
            for _ in range(count):
                inventories[match_id, 0] = inventory
                folds[match_id] = fold
                match_id += 1
    backbone = BackboneSelection(
        tuple(range(1, 7)),
        len(inventories),
        {"train": 50, "validation": 50, "test": 50},
        (),
    )

    default, _, _ = complete_default_core(
        backbone,
        inventories,
        folds,
        graph,
        costs,
        20,
        target_cost=18,
    )

    assert {9, 10} <= set(default)
    total_cost = sum(costs[item_id] for item_id in default)
    assert 18 * 0.9 <= total_cost <= 18 * 1.1


def test_default_completion_can_stop_at_supported_backbone_in_budget() -> None:
    costs = dict.fromkeys(range(1, 7), 4)
    graph = ItemGraph.from_assets([
        {
            "id": item_id,
            "class_name": f"item_{item_id}",
            "name": f"Item {item_id}",
            "cost": cost,
            "item_tier": 3,
            "item_slot_type": "weapon",
            "component_items": [],
            "shopable": True,
            "disabled": False,
            "is_active_item": False,
            "is_unique": True,
        }
        for item_id, cost in costs.items()
    ])
    inventories: dict[tuple[int, int], tuple[int, ...]] = {}
    folds: dict[int, str] = {}
    match_id = 1
    for fold in ("train", "validation", "test"):
        for _ in range(20):
            inventories[match_id, 0] = tuple(costs)
            folds[match_id] = fold
            match_id += 1
    backbone = BackboneSelection(
        tuple(costs),
        len(inventories),
        {"train": 20, "validation": 20, "test": 20},
        (),
    )

    default, _, _ = complete_default_core(
        backbone,
        inventories,
        folds,
        graph,
        costs,
        40,
        target_cost=25,
    )

    assert default == tuple(costs)


def test_default_completion_can_choose_nine_items_to_reach_budget() -> None:
    costs = {**dict.fromkeys(range(1, 7), 1), **dict.fromkeys(range(7, 10), 6)}
    graph = ItemGraph.from_assets([
        {
            "id": item_id,
            "class_name": f"item_{item_id}",
            "name": f"Item {item_id}",
            "cost": cost,
            "item_tier": 3,
            "item_slot_type": "weapon",
            "component_items": [],
            "shopable": True,
            "disabled": False,
            "is_active_item": False,
            "is_unique": True,
        }
        for item_id, cost in costs.items()
    ])
    inventories: dict[tuple[int, int], tuple[int, ...]] = {}
    folds: dict[int, str] = {}
    match_id = 1
    for fold in ("train", "validation", "test"):
        for _ in range(20):
            inventories[match_id, 0] = tuple(costs)
            folds[match_id] = fold
            match_id += 1
    backbone = BackboneSelection(
        tuple(range(1, 7)),
        len(inventories),
        {"train": 20, "validation": 20, "test": 20},
        (),
    )

    default, _, _ = complete_default_core(
        backbone,
        inventories,
        folds,
        graph,
        costs,
        40,
        target_cost=24,
    )

    assert default == tuple(range(1, 10))


def _contrast_rows(*, positive: bool) -> list[dict[str, object]]:
    return [
        {
            "match_id": index + 1,
            "player_slot": 0,
            "fold": ("train", "validation", "test")[index // 800],
            "item_id": 10 if index % 2 == 0 else 20,
            "won": int(index % 2 == 0) if positive else (index // 2) % 2,
            "average_badge": 90,
            "phase": 2,
            "buy_time": 1_200,
            "own_net_worth_at_buy": 20_000,
            "state_observed_at_s": 1_190,
            "own_team_net_worth": 100_000,
            "enemy_team_net_worth": 100_000,
            "team_net_worth_lead": 0,
            "state_age_s": 10,
            "prior_catalog_spend": 18_000,
            "prior_purchase_count": 6,
        }
        for index in range(2_400)
    ]


def test_cross_fitted_dr_contrast_rejects_a_stable_like_state_tie() -> None:
    contrast = cross_fitted_dr_contrast(
        pl.DataFrame(_contrast_rows(positive=False)), 10, 20
    )

    assert not contrast.admitted
    assert contrast.estimate == 0
    assert "positive_advantage" in contrast.failed_gates


def test_cross_fitted_dr_contrast_admits_positive_train_and_validation() -> None:
    contrast = cross_fitted_dr_contrast(
        pl.DataFrame(_contrast_rows(positive=True)), 10, 20
    )

    assert contrast.admitted
    assert contrast.estimate == 1
    assert contrast.overlap == 1
    assert contrast.effective_support >= 20
    assert set(contrast.fold_estimates) == {"train", "validation", "test"}


def test_test_outcomes_do_not_admit_optional_core_substitutions() -> None:
    rows = _contrast_rows(positive=True)
    baseline = cross_fitted_dr_contrast(pl.DataFrame(rows), 10, 20)
    without_test = cross_fitted_dr_contrast(
        pl.DataFrame([row for row in rows if row["fold"] != "test"]),
        10,
        20,
    )

    assert baseline.admitted == without_test.admitted
    assert baseline.estimate == without_test.estimate
    assert baseline.interval == without_test.interval
    assert set(without_test.fold_estimates) == {"train", "validation"}


def _item_graph(components: dict[int, tuple[int, ...]]) -> ItemGraph:
    return ItemGraph.from_assets([
        {
            "id": item_id,
            "class_name": f"item_{item_id}",
            "name": f"Item {item_id}",
            "cost": 800,
            "item_slot_type": "weapon",
            "item_tier": 1,
            "component_items": [
                f"item_{component_id}" for component_id in components.get(item_id, ())
            ],
            "shopable": True,
            "disabled": False,
            "is_active_item": False,
            "is_unique": True,
        }
        for item_id in range(1, 10)
    ])


def test_tier_policy_uses_train_and_validation_only() -> None:
    assets = [
        {
            "id": tier,
            "class_name": f"item_{tier}",
            "name": f"Tier {tier}",
            "cost": tier * 500,
            "item_slot_type": "weapon",
            "item_tier": tier,
            "component_items": [],
            "shopable": True,
            "disabled": False,
            "is_active_item": False,
            "is_unique": True,
        }
        for tier in range(1, 5)
    ]
    assets.append({
        **assets[0],
        "id": 6,
        "class_name": "item_6",
        "name": "Tier 1 Without Reliable Timing",
    })
    rows = [
        {
            "item_id": tier,
            "tier": tier,
            "training_adopter_matches": 30,
            "validation_adopter_matches": 30,
            "test_adopter_matches": test_support,
            "selection_median_valid_buy_net_worth": tier * 1_000.0,
            "selection_median_buy_time_s": tier * 60.0,
            "selection_adopter_matches": 60,
            "selection_valid_buy_nw_observations": 60,
            "training_valid_buy_nw_observations": 30,
            "validation_valid_buy_nw_observations": 30,
            "selection_buy_nw_q25": tier * 900.0,
            "selection_buy_nw_q75": tier * 1_100.0,
            "training_buy_nw_q25": tier * 900.0,
            "training_buy_nw_q75": tier * 1_100.0,
            "validation_buy_nw_q25": tier * 900.0,
            "validation_buy_nw_q75": tier * 1_100.0,
        }
        for tier, test_support in zip(range(1, 5), (0, 100, 1_000, 10_000), strict=True)
    ]
    rows.append({
        **rows[0],
        "item_id": 6,
        "training_adopter_matches": 40,
        "validation_adopter_matches": 31,
        "selection_adopter_matches": 71,
        "selection_valid_buy_nw_observations": 49,
        "validation_valid_buy_nw_observations": 19,
        "selection_median_valid_buy_net_worth": 500.0,
    })
    fold_eligible = {"train": 100, "validation": 100, "test": 10_000}
    graph = ItemGraph.from_assets(assets)

    selected = _tier_policy(
        12,
        pl.DataFrame(rows),
        (),
        frozenset(),
        graph,
        fold_eligible,
    )

    assert selected["item_ids_by_tier"] == {
        "1": [1, 6],
        "2": [2],
        "3": [3],
        "4": [4],
    }

    weak_validation = pl.DataFrame([
        {**row, "validation_adopter_matches": 1} if row["tier"] == 1 else row
        for row in rows
    ])
    with pytest.raises(UnsupportedBuildPathError, match="Tier 1"):
        _tier_policy(
            12,
            weak_validation,
            (),
            frozenset(),
            graph,
            fold_eligible,
        )


def test_tier_policy_requires_one_visible_upgrade_route() -> None:
    assets = [
        {
            "id": item_id,
            "class_name": f"item_{item_id}",
            "name": f"Item {item_id}",
            "cost": tier * 500,
            "item_slot_type": "weapon",
            "item_tier": tier,
            "component_items": (["item_1"] if item_id in {2, 3} else []),
            "shopable": True,
            "disabled": False,
            "is_active_item": False,
            "is_unique": True,
        }
        for item_id, tier in ((1, 1), (2, 2), (3, 3), (4, 3), (5, 4))
    ]
    rows = [
        {
            "item_id": item_id,
            "tier": tier,
            "training_adopter_matches": 30,
            "validation_adopter_matches": 30,
            "test_adopter_matches": 0,
            "selection_median_valid_buy_net_worth": tier * 1_000.0,
            "selection_median_buy_time_s": tier * 60.0,
        }
        for item_id, tier in ((1, 1), (2, 2), (4, 3), (5, 4))
    ]

    selected = _tier_policy(
        12,
        pl.DataFrame(rows),
        (),
        frozenset(),
        ItemGraph.from_assets(assets),
        {"train": 100, "validation": 100, "test": 0},
    )

    assert selected["item_ids_by_tier"]["1"] == [1]


def test_subset_dp_maximizes_pairwise_target_precedence() -> None:
    precedence = Counter({
        (1, 2): 10,
        (2, 3): 9,
        (1, 3): 8,
        (3, 1): 2,
        (3, 2): 1,
    })

    best, runner, best_score, runner_score = _maximum_agreement_orders(
        (3, 1, 2), precedence
    )

    assert best == (1, 2, 3)
    assert best_score == 27
    assert runner != best
    assert runner_score < best_score


def test_core_order_rejects_pairwise_winner_outside_soul_window() -> None:
    con = duckdb.connect()
    con.execute(
        "CREATE TABLE first_purchases ("
        "match_id BIGINT, player_slot INTEGER, hero_id INTEGER, "
        "item_id INTEGER, buy_time DOUBLE)"
    )
    con.executemany(
        "INSERT INTO first_purchases VALUES (?, ?, ?, ?, ?)",
        [
            (match_id, 0, 81, item_id, float(item_id))
            for match_id in range(30)
            for item_id in range(1, 9)
        ],
    )
    priorities = {
        item_id: (float(item_id), float(item_id), item_id) for item_id in range(1, 10)
    }
    window_bounds = {
        **dict.fromkeys(range(1, 7), (0.0, 100.0)),
        7: (7.0, 8.0),
        8: (0.0, 6.5),
    }

    best, diagnostics = _core_target_order(
        con,
        81,
        {"item_ids": list(range(1, 9)), "joint_matches": 30},
        {(match_id, 0) for match_id in range(30)},
        _item_graph({}),
        priorities,
        window_bounds,
    )

    assert best == (1, 2, 3, 4, 5, 6, 8, 7)
    assert diagnostics["method"] == (
        "window_constrained_pairwise_target_precedence_subset_dp"
    )
    assert diagnostics["window_constraint"] == ("nondecreasing_first_ownership_iqr")


def test_patch_content_hash_normalizes_steam_cdn_routing() -> None:
    akamai = '<img src="https://clan.akamai.steamstatic.com/images/x.png">Notes'
    fastly = akamai.replace("akamai", "fastly")

    assert _patch_content_sha256(akamai) == _patch_content_sha256(fastly)
    assert _patch_content_sha256(akamai) != _patch_content_sha256(
        fastly.replace("Notes", "Changed notes")
    )


def test_component_expanded_default_path_buys_missing_components_first() -> None:
    metrics = pl.DataFrame([
        {
            "item_id": item_id,
            "selection_median_valid_buy_net_worth": item_id * 1_000,
            "selection_median_buy_time_s": item_id * 60,
        }
        for item_id in range(2, 10)
    ])

    path = _expanded_default_path(
        tuple(range(2, 10)),
        metrics,
        _item_graph({2: (1,)}),
    )

    assert path == list(range(1, 10))


def test_sequence_policy_uses_train_rows_and_emits_supported_backoffs() -> None:
    con = duckdb.connect()
    con.execute(
        "CREATE TABLE first_purchases ("
        "match_id BIGINT, player_slot INTEGER, fold VARCHAR, hero_id INTEGER, "
        "item_id INTEGER, buy_time DOUBLE)"
    )
    con.executemany(
        "INSERT INTO first_purchases VALUES (?, ?, ?, ?, ?, ?)",
        [
            (match_id, 0, fold, 12, item_id, buy_time)
            for match_id in range(30)
            for item_id, buy_time in ((1, 10.0), (2, 20.0))
            for fold in (("train",) if match_id < 25 else ("test",))
        ],
    )

    rows = _sequence_rows(con, 12)

    assert {row["level"] for row in rows} == {
        "first_previous_position",
        "previous_position",
        "position",
        "popularity",
    }
    assert all(row["support"] >= 20 for row in rows)
    assert all(row["context_support"] >= row["support"] for row in rows)


def test_sequence_policy_uses_only_selected_build_path_members() -> None:
    con = duckdb.connect()
    con.execute(
        "CREATE TABLE first_purchases ("
        "match_id BIGINT, player_slot INTEGER, fold VARCHAR, hero_id INTEGER, "
        "item_id INTEGER, buy_time DOUBLE)"
    )
    con.executemany(
        "INSERT INTO first_purchases VALUES (?, ?, 'train', 12, ?, ?)",
        [
            (match_id, 0, item_id, buy_time)
            for match_id in range(40)
            for item_id, buy_time in (
                ((1, 10.0), (2, 20.0)) if match_id < 20 else ((3, 10.0), (4, 20.0))
            )
        ],
    )

    rows = _sequence_rows(
        con,
        12,
        frozenset((match_id, 0) for match_id in range(20)),
    )

    assert {row["next_item_id"] for row in rows} == {1, 2}


def test_situational_candidates_are_audited_but_abstain_without_uncertainty_gate(
    tmp_path: Path,
) -> None:
    paths = RunPaths.create(tmp_path, "run")
    pl.DataFrame([
        {
            "hero_id": 12,
            "item_id": 3,
            "enemy_hero_id": 7,
            "scope": "same_lane",
            "phase": 1,
            "tier": 2,
            "observations": 40,
        }
    ]).write_csv(paths.tables / "matchup_interactions.csv")
    pl.DataFrame([
        {
            "hero_id": 12,
            "item_id": 3,
            "effective_support": 30.0,
            "state_coverage": 0.8,
        }
    ]).write_csv(paths.tables / "state_overlap_diagnostics.csv")
    pl.DataFrame([
        {
            "hero_id": 12,
            "scope": "same_lane",
            "spearman": 0.5,
            "sign_agreement": 0.75,
        }
    ]).write_csv(paths.tables / "matchup_temporal_stability.csv")
    assets = [{"id": 3, "description": {"desc": "Applies healing reduction."}}]

    enemy_threat_evidence: dict[int, dict[str, tuple[str, ...]]] = {
        7: {"healing": ("asset:ability:7:description",)}
    }
    policy = _situational_policy(
        paths,
        12,
        assets,
        enemy_threat_evidence=enemy_threat_evidence,
    )

    assert policy["branches"] == []
    candidate = policy["candidate_audit"]["sample"][0]
    assert candidate["threat"] == "healing"
    assert not candidate["gates"]["bounded_comparative_uncertainty"]
    assert policy["abstentions"]


def test_situational_branch_requires_untouched_fold_evidence(
    tmp_path: Path,
) -> None:
    paths = RunPaths.create(tmp_path, "run")
    pl.DataFrame([
        {
            "hero_id": 12,
            "item_id": 3,
            "enemy_hero_id": 7,
            "scope": "same_lane",
            "phase": 1,
            "tier": 2,
            "observations": 40,
            "same_opportunity": True,
            "comparator_item_id": 4,
            "comparison_support": 30,
            "comparative_interval_low": 0.01,
            "comparative_interval_high": 0.06,
        }
    ]).write_csv(paths.tables / "matchup_interactions.csv")
    pl.DataFrame([
        {
            "hero_id": 12,
            "item_id": 3,
            "effective_support": 30.0,
            "state_coverage": 0.8,
        }
    ]).write_csv(paths.tables / "state_overlap_diagnostics.csv")
    pl.DataFrame([
        {
            "hero_id": 12,
            "scope": "same_lane",
            "spearman": 0.5,
            "sign_agreement": 0.75,
        }
    ]).write_csv(paths.tables / "matchup_temporal_stability.csv")
    assets = [
        {"id": 3, "description": {"desc": "Applies healing reduction."}},
        {"id": 4, "description": {"desc": "Gain Weapon Damage."}},
    ]

    enemy_threat_evidence: dict[int, dict[str, tuple[str, ...]]] = {
        7: {"healing": ("asset:ability:7:description",)}
    }
    policy = _situational_policy(
        paths,
        12,
        assets,
        enemy_threat_evidence=enemy_threat_evidence,
    )

    assert policy["branches"] == []
    assert not policy["candidate_audit"]["sample"][0]["gates"]["test_support"]

    missing_comparator = _situational_policy(
        paths,
        12,
        assets,
        eligible_item_ids=frozenset({3}),
        enemy_threat_evidence=enemy_threat_evidence,
    )

    assert missing_comparator["branches"] == []

    pl.DataFrame([
        {
            "hero_id": 12,
            "item_id": 3,
            "enemy_hero_id": 7,
            "scope": "same_lane",
            "phase": 1,
            "tier": 2,
            "observations": 40,
            "same_opportunity": True,
            "comparator_item_id": 4,
            "comparison_support": 30,
            "comparative_interval_low": -0.01,
            "comparative_interval_high": 0.06,
        }
    ]).write_csv(paths.tables / "matchup_interactions.csv")

    unsupported = _situational_policy(
        paths,
        12,
        assets,
        enemy_threat_evidence=enemy_threat_evidence,
    )

    assert unsupported["branches"] == []
    assert not unsupported["candidate_audit"]["sample"][0]["gates"][
        "comparative_advantage"
    ]


def test_situational_admission_requires_all_three_fold_cells(tmp_path: Path) -> None:
    paths = RunPaths.create(tmp_path, "run")
    decisions = []
    enemies = []
    compositions = []
    match_id = 1
    for fold in ("train", "validation", "test"):
        for item_id in (3, 4):
            for offset in range(200):
                target = item_id == 3
                won = offset < (180 if target else 40)
                decisions.append({
                    "match_id": match_id,
                    "player_slot": 0,
                    "hero_id": 12,
                    "phase": 1,
                    "tier": 2,
                    "item_id": item_id,
                    "won": won,
                    "team_id": 0,
                    "assigned_lane": 1,
                    "fold": fold,
                    "own_net_worth_at_buy": 10_000,
                    "team_net_worth_lead": 0,
                })
                enemies.append({
                    "match_id": match_id,
                    "team_id": 1,
                    "assigned_lane": 1,
                    "hero_id": 7,
                })
                compositions.append({
                    "match_id": match_id,
                    "team_id": 1,
                    "hero_ids": [7],
                })
                match_id += 1
    con = duckdb.connect()
    try:
        con.register("decisions_source", pl.DataFrame(decisions))
        con.register("enemies_source", pl.DataFrame(enemies))
        con.register("compositions_source", pl.DataFrame(compositions))
        con.execute(
            "CREATE TABLE decision_opportunities AS SELECT * FROM decisions_source"
        )
        con.execute("CREATE TABLE player_matches AS SELECT * FROM enemies_source")
        con.execute("CREATE TABLE compositions AS SELECT * FROM compositions_source")
        admitted_policy = _situational_policy(
            paths,
            12,
            [
                {"id": 3, "description": {"desc": "Applies healing reduction."}},
                {"id": 4, "description": {"desc": "Gain Weapon Damage."}},
            ],
            eligible_item_ids=frozenset({3}),
            comparator_item_ids=frozenset({4}),
            enemy_threat_evidence={7: {"healing": ("asset:ability:7:description",)}},
            con=con,
        )
        con.execute(
            """
            UPDATE decision_opportunities
            SET won = CASE WHEN item_id = 3 THEN false ELSE true END
            WHERE fold = 'test'
            """
        )
        policy = _situational_policy(
            paths,
            12,
            [
                {"id": 3, "description": {"desc": "Applies healing reduction."}},
                {"id": 4, "description": {"desc": "Gain Weapon Damage."}},
            ],
            eligible_item_ids=frozenset({3}),
            comparator_item_ids=frozenset({4}),
            enemy_threat_evidence={7: {"healing": ("asset:ability:7:description",)}},
            con=con,
        )
        invalid_comparator = _situational_policy(
            paths,
            12,
            [
                {"id": 3, "description": {"desc": "Applies healing reduction."}},
                {"id": 4, "description": {"desc": "Gain Weapon Damage."}},
            ],
            eligible_item_ids=frozenset({3}),
            comparator_item_ids=frozenset({99}),
            enemy_threat_evidence={7: {"healing": ("asset:ability:7:description",)}},
            con=con,
        )
        replacement_assets = [
            {
                "id": item_id,
                "class_name": f"item_{item_id}",
                "name": f"Item {item_id}",
                "cost": 1_250,
                "item_tier": 2,
                "item_slot_type": "spirit",
                "component_items": [],
                "shopable": True,
                "disabled": False,
                "is_active_item": item_id != 4,
                "is_unique": True,
            }
            for item_id in range(3, 9)
        ]
        replacement_graph = ItemGraph.from_assets(replacement_assets)
        invalid_replacement = _situational_policy(
            paths,
            12,
            [
                {"id": 3, "description": {"desc": "Applies healing reduction."}},
                {"id": 4, "description": {"desc": "Gain Weapon Damage."}},
            ],
            eligible_item_ids=frozenset({3}),
            comparator_item_ids=frozenset({4}),
            default_item_ids=(4, 5, 6, 7, 8),
            graph=replacement_graph,
            priorities={
                item_id: (float(item_id), float(item_id), item_id)
                for item_id in replacement_graph.nodes
            },
            enemy_threat_evidence={7: {"healing": ("asset:ability:7:description",)}},
            con=con,
        )
    finally:
        con.close()

    assert len(admitted_policy["branches"]) == 1
    assert any(
        candidate["admitted"]
        for candidate in admitted_policy["candidate_audit"]["sample"]
    )
    assert policy["branches"] == []
    candidate = policy["candidate_audit"]["sample"][0]
    assert candidate["fold_comparative_estimates"]["train"] > 0
    assert candidate["fold_comparative_estimates"]["validation"] > 0
    assert candidate["fold_comparative_estimates"]["test"] < 0
    assert candidate["fold_support"]["train"] == {
        "item": 200,
        "comparator": 200,
    }
    assert not candidate["gates"]["test_advantage"]
    assert invalid_comparator["branches"] == []
    assert invalid_replacement["branches"] == []
    assert not invalid_replacement["candidate_audit"]["sample"][0]["gates"][
        "replacement_legality"
    ]
