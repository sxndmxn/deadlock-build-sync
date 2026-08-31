from collections import Counter
from itertools import combinations
from types import SimpleNamespace
from typing import cast
from unittest.mock import patch

import duckdb
import polars as pl

from deadlock_build_sync.mechanics import ItemGraph
from deadlock_build_sync.offline.build_paths import DiscoveredBuildPath
from deadlock_build_sync.offline.config import sha256_json
from deadlock_build_sync.offline.core_policy import (
    BackboneSelection,
    _bundle_support_by_size_and_fold,
    complete_default_core,
    select_supported_backbone,
)
from deadlock_build_sync.offline.production_evidence import (
    UnsupportedBuildPathError,
    _core_economy_reference,
    _HeroExportContext,
    _item_payload,
    _parallel_hero_export,
    _path_cohort_summary,
    _path_payloads,
    _situational_selection_matchups,
)
from deadlock_build_sync.offline.production_policy import _purchase_window_bounds
from tests.offline.production_evidence_fixtures import (
    _item_metric_row,
)


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
    assets: dict[int, dict[str, object]] = {40: {"id": 40, "name": "Frozen Shelter"}}
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
    assert sha256_json(supported) == (
        "51e300997477414bd41771eb506aaf5dfb8b652ae8137ab9d8a6c304eba76aa1"
    )
    assert weak["imbue_target_ability_id"] is None
    assert weak["imbue_observations"] == 0


def test_purchase_windows_require_complete_stable_fold_evidence() -> None:
    base = _item_metric_row()
    changes: tuple[dict[str, object], ...] = (
        {"selection_valid_buy_nw_observations": 0},
        {"training_valid_buy_nw_observations": 0},
        {"validation_valid_buy_nw_observations": 0},
        {"training_buy_nw_q25": None},
        {"training_buy_nw_q75": None},
        {"validation_buy_nw_q25": None},
        {"validation_buy_nw_q75": None},
        {"training_buy_nw_q25": 15_000.0},
        {"selection_buy_nw_q25": None},
        {"selection_buy_nw_q75": None},
    )
    rows = [
        base,
        *(
            {**base, "item_id": 200 + index, **change}
            for index, change in enumerate(changes)
        ),
    ]

    result = _purchase_window_bounds(pl.DataFrame(rows, strict=False))
    assert result == {101: (10_000.0, 14_000.0)}


def test_hero_export_runs_eight_workers_and_preserves_order() -> None:
    jobs: list[tuple[int, dict[str, object]]] = [
        (index, {"id": index}) for index in range(1, 11)
    ]
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
        "_HeroExportContext",
        SimpleNamespace(
            mechanics_assets_by_id={},
            folds_by_match={1: "train", 2: "train"},
        ),
    )
    inventories: dict[tuple[int, int], tuple[int, ...]] = {
        (1, 0): (101,),
        (2, 0): (102,),
    }

    def path_label(
        connection: duckdb.DuckDBPyConnection,
        path: DiscoveredBuildPath,
        mechanics_assets: dict[int, dict[str, object]],
    ) -> str:
        assert connection is con
        assert mechanics_assets is context.mechanics_assets_by_id
        return {"bad": "Bad", "good": "Good"}[path.path_id]

    def build_payload(*args: object, **kwargs: object) -> dict[str, str]:
        path = cast("DiscoveredBuildPath", args[3])
        assert args[:3] == (con, 12, {"id": 12})
        assert args[4] in {"Bad", "Good"}
        assert args[5] == Counter({"Bad": 1, "Good": 1})
        assert args[6:] == (inventories, context, None, None)
        assert kwargs == {}
        if path.path_id == "bad":
            raise UnsupportedBuildPathError("unsupported tier")
        return {"path_id": path.path_id}

    con = duckdb.connect()
    try:
        with (
            patch(
                "deadlock_build_sync.offline.production_evidence._path_label",
                side_effect=path_label,
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
                inventories,
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
    assert sha256_json(reference) == (
        "7032de3aecc9f84c34ee90cc59b832babe5dad8c1594abf046f0f3bdd72f2672"
    )


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
