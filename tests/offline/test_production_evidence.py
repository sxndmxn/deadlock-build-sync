from collections import Counter
from itertools import combinations, islice
from pathlib import Path
from unittest.mock import patch

import duckdb
import polars as pl

from deadlock_build_sync.mechanics import ItemGraph
from deadlock_build_sync.offline.config import RunPaths
from deadlock_build_sync.offline.core_policy import (
    BackboneSelection,
    complete_default_core,
    cross_fitted_dr_contrast,
    select_supported_backbone,
)
from deadlock_build_sync.offline.production_evidence import (
    _core_target_order,
    _duplicate_free_core_candidates,
    _expanded_default_path,
    _maximum_agreement_orders,
    _parallel_hero_export,
    _patch_content_sha256,
    _sequence_rows,
    _situational_policy,
    _top_core_candidates,
)


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


def test_supported_backbone_uses_generic_mechanics_and_temporal_support() -> None:
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

    nucleus = set(range(1, 6))
    assert set(backbone.item_ids) == nucleus
    assert len(backbone.item_ids) == 5
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


def test_cross_fitted_dr_contrast_admits_a_stable_like_state_tie() -> None:
    rows = [
        {
            "match_id": index + 1,
            "player_slot": 0,
            "fold": ("train", "validation", "test")[index // 800],
            "item_id": 10 if index % 2 == 0 else 20,
            "won": (index // 2) % 2,
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

    contrast = cross_fitted_dr_contrast(pl.DataFrame(rows), 10, 20)

    assert contrast.admitted
    assert contrast.estimate == 0
    assert contrast.overlap == 1
    assert contrast.effective_support >= 20
    assert set(contrast.fold_estimates) == {"train", "validation", "test"}


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


def test_core_candidates_are_supported_and_deterministically_ranked() -> None:
    first = tuple(range(1, 9))
    second = (*range(1, 8), 9)
    third = (*range(1, 8), 10)
    sparse = (*range(1, 8), 11)

    candidates = _top_core_candidates(
        [first] * 30 + [second] * 20 + [third] * 20 + [sparse] * 19,
        dict.fromkeys(range(1, 12), 1),
        8,
    )

    assert candidates == [
        {"item_ids": list(first), "joint_matches": 30},
        {"item_ids": list(second), "joint_matches": 20},
        {"item_ids": list(third), "joint_matches": 20},
    ]


def test_core_candidate_cap_is_applied_after_budget_filter() -> None:
    over_budget = tuple(range(1, 9))
    within_budget = (*range(1, 8), 9)

    candidates = _top_core_candidates(
        [over_budget] * 40 + [within_budget] * 30,
        {**dict.fromkeys(range(1, 10), 1), 8: 100},
        8,
    )

    assert candidates == [{"item_ids": list(within_budget), "joint_matches": 30}]


def test_core_candidate_cap_is_applied_after_path_legality_filter() -> None:
    invalid_suffixes = list(islice(combinations(range(3, 16), 6), 65))
    valid = tuple(range(2, 10))
    inventories = [
        inventory for suffix in invalid_suffixes for inventory in [(1, 2, *suffix)] * 21
    ] + [valid] * 20
    graph = ItemGraph.from_assets([
        {
            "id": item_id,
            "class_name": f"item_{item_id}",
            "name": f"Item {item_id}",
            "cost": 1,
            "item_slot_type": "weapon",
            "item_tier": 1,
            "component_items": ["item_1"] if item_id == 2 else [],
            "shopable": True,
            "disabled": False,
            "is_active_item": False,
            "is_unique": True,
        }
        for item_id in range(1, 16)
    ])
    priorities = {
        item_id: (float(item_id), float(item_id), item_id) for item_id in graph.nodes
    }

    candidates = _top_core_candidates(
        inventories,
        dict.fromkeys(range(1, 16), 1),
        100,
        graph=graph,
        priorities=priorities,
    )

    assert candidates == [{"item_ids": list(valid), "joint_matches": 20}]


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
            "median_valid_buy_net_worth": item_id * 1_000,
            "median_buy_time_s": item_id * 60,
        }
        for item_id in range(2, 10)
    ])

    path = _expanded_default_path(
        [{"item_ids": list(range(2, 10)), "joint_matches": 30}],
        metrics,
        _item_graph({2: (1,)}),
    )

    assert path == list(range(1, 10))


def test_duplicate_free_core_filter_uses_next_supported_candidate() -> None:
    metrics = pl.DataFrame([
        {
            "item_id": item_id,
            "median_valid_buy_net_worth": 1_000 if item_id == 2 else item_id * 2_000,
            "median_buy_time_s": item_id * 60,
        }
        for item_id in range(1, 10)
    ])
    candidates = [
        {"item_ids": list(range(1, 9)), "joint_matches": 30},
        {"item_ids": list(range(2, 10)), "joint_matches": 25},
    ]
    graph = _item_graph({2: (1,)})

    filtered = _duplicate_free_core_candidates(candidates, metrics, graph)
    path = _expanded_default_path(filtered, metrics, graph)

    assert filtered == [candidates[1]]
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

    policy = _situational_policy(paths, 12, assets)

    assert policy["branches"] == []
    assert policy["candidate_audit"][0]["threat"] == "healing"
    assert not policy["candidate_audit"][0]["gates"]["bounded_comparative_uncertainty"]
    assert policy["abstentions"]


def test_situational_branch_is_emitted_only_when_every_gate_is_present(
    tmp_path: Path,
) -> None:
    paths = RunPaths.create(tmp_path, "run")
    pl.DataFrame([
        {
            "hero_id": 12,
            "item_id": 3,
            "enemy_hero_id": 7,
            "scope": "same_lane",
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
        {"id": 4, "description": {"desc": "Plain damage."}},
    ]

    policy = _situational_policy(paths, 12, assets)

    assert len(policy["branches"]) == 1
    assert policy["branches"][0]["comparator"] == ("same-opportunity item 4 or save")
    assert policy["branches"][0]["failure_condition"]
    assert policy["candidate_audit"][0]["admitted"]
    assert policy["abstentions"] == []

    missing_comparator = _situational_policy(
        paths,
        12,
        assets,
        eligible_item_ids=frozenset({3}),
    )

    assert missing_comparator["branches"] == []
    assert missing_comparator["candidate_audit"] == []

    pl.DataFrame([
        {
            "hero_id": 12,
            "item_id": 3,
            "enemy_hero_id": 7,
            "scope": "same_lane",
            "observations": 40,
            "same_opportunity": True,
            "comparator_item_id": 4,
            "comparison_support": 30,
            "comparative_interval_low": -0.01,
            "comparative_interval_high": 0.06,
        }
    ]).write_csv(paths.tables / "matchup_interactions.csv")

    unsupported = _situational_policy(paths, 12, assets)

    assert unsupported["branches"] == []
    assert not unsupported["candidate_audit"][0]["gates"]["comparative_advantage"]
