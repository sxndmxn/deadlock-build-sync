from pathlib import Path

import duckdb
import polars as pl

from deadlock_build_sync.mechanics import ItemGraph
from deadlock_build_sync.offline.config import RunPaths
from deadlock_build_sync.value_validation import (
    number,
    require_object_dict,
    require_object_rows,
)
from tests.offline.production_evidence_fixtures import (
    _candidate_sample,
    _register_situational_tables,
)
from tools.comparisons.legacy.production_evidence import (
    _sequence_rows,
    _situational_policy,
)


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
    assets: list[dict[str, object]] = [
        {"id": 3, "description": {"desc": "Applies healing reduction."}}
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

    assert require_object_rows(policy["branches"]) == []
    candidate = _candidate_sample(policy)[0]
    gates = require_object_dict(candidate["gates"])
    assert candidate["threat"] == "healing"
    assert not gates["bounded_comparative_uncertainty"]
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
    assets: list[dict[str, object]] = [
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

    assert require_object_rows(policy["branches"]) == []
    candidate = _candidate_sample(policy)[0]
    gates = require_object_dict(candidate["gates"])
    assert not gates["test_support"]

    missing_comparator = _situational_policy(
        paths,
        12,
        assets,
        eligible_item_ids=frozenset({3}),
        enemy_threat_evidence=enemy_threat_evidence,
    )

    assert require_object_rows(missing_comparator["branches"]) == []

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

    assert require_object_rows(unsupported["branches"]) == []
    unsupported_candidate = _candidate_sample(unsupported)[0]
    unsupported_gates = require_object_dict(unsupported_candidate["gates"])
    assert not unsupported_gates["comparative_advantage"]


def test_situational_admission_requires_all_three_fold_cells(tmp_path: Path) -> None:
    paths = RunPaths.create(tmp_path, "run")
    con = duckdb.connect()
    try:
        _register_situational_tables(con)
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
        replacement_assets: list[dict[str, object]] = [
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

    assert len(require_object_rows(admitted_policy["branches"])) == 1
    assert any(
        candidate["admitted"] for candidate in _candidate_sample(admitted_policy)
    )
    assert require_object_rows(policy["branches"]) == []
    candidate = _candidate_sample(policy)[0]
    estimates = require_object_dict(candidate["fold_comparative_estimates"])
    fold_support = require_object_dict(candidate["fold_support"])
    gates = require_object_dict(candidate["gates"])
    assert number(estimates["train"]) > 0
    assert number(estimates["validation"]) > 0
    assert number(estimates["test"]) < 0
    assert fold_support["train"] == {
        "item": 200,
        "comparator": 200,
    }
    assert not gates["test_advantage"]
    assert require_object_rows(invalid_comparator["branches"]) == []
    assert require_object_rows(invalid_replacement["branches"]) == []
    replacement_candidate = _candidate_sample(invalid_replacement)[0]
    replacement_gates = require_object_dict(replacement_candidate["gates"])
    assert not replacement_gates["replacement_legality"]
