from collections import Counter

import duckdb
import polars as pl
import pytest

from deadlock_build_sync.mechanics import ItemGraph
from deadlock_build_sync.offline.build_paths import DiscoveredBuildPath
from deadlock_build_sync.offline.config import sha256_json
from deadlock_build_sync.offline.core_policy import (
    cross_fitted_dr_contrast,
)
from deadlock_build_sync.offline.production_evidence import (
    UnsupportedBuildPathError,
    _core_target_order,
    _expanded_default_path,
    _maximum_agreement_orders,
    _patch_content_sha256,
    _sequence_rows,
    _tier_policy,
)
from deadlock_build_sync.offline.production_policy import _path_label
from deadlock_build_sync.value_validation import (
    integer,
    require_object_dict,
)
from tests.offline.production_evidence_fixtures import (
    _contrast_rows,
    _item_graph,
)


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


def test_tier_policy_uses_train_and_validation_only() -> None:
    assets: list[dict[str, object]] = [
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
    assert sha256_json(selected) == (
        "91973ccfc612da8c0a77c630f7bd8707e8158aad1ff44698d64d468c1121df80"
    )

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
    assets: list[dict[str, object]] = [
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

    item_ids_by_tier = require_object_dict(selected["item_ids_by_tier"])
    assert item_ids_by_tier["1"] == [1]


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


def test_path_label_prefers_imbue_then_slot_item_and_default() -> None:
    con = duckdb.connect()
    con.execute(
        "CREATE TABLE purchases ("
        "match_id BIGINT, player_slot INTEGER, imbued_ability_id INTEGER)"
    )
    con.execute("CREATE TABLE match_folds (match_id BIGINT, fold VARCHAR)")
    con.executemany(
        "INSERT INTO match_folds VALUES (?, ?)",
        [(1, "train"), (2, "train")],
    )
    con.executemany(
        "INSERT INTO purchases VALUES (?, ?, ?)",
        [(1, 0, 99), (2, 0, 99)],
    )
    members = frozenset({(1, 0), (2, 0)})
    ability_path = DiscoveredBuildPath("ability", members, (10,), {"train": 2}, {})

    assert _path_label(con, ability_path, {99: {"name": " Mini Turret "}}) == (
        "Mini Turret"
    )

    con.execute("DELETE FROM purchases")
    slot_path = DiscoveredBuildPath("slot", members, (10, 11), {}, {})
    assert (
        _path_label(
            con,
            slot_path,
            {
                10: {"item_slot_type": "weapon"},
                11: {"item_slot_type": "weapon"},
            },
        )
        == "Weapon Core"
    )

    item_path = DiscoveredBuildPath("item", members, (12,), {}, {})
    assert _path_label(con, item_path, {12: {"name": "Named Item"}}) == "Named Item"

    default_path = DiscoveredBuildPath("default", members, (), {}, {})
    assert _path_label(con, default_path, {}) == "Evidence Default"


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
    assert all(integer(row["support"]) >= 20 for row in rows)
    assert all(
        integer(row["context_support"]) >= integer(row["support"]) for row in rows
    )
