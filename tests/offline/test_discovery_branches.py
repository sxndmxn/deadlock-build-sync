from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import duckdb
import numpy as np
import polars as pl
from threadpoolctl import threadpool_limits

from deadlock_build_sync.offline import discovery_branches as branches
from deadlock_build_sync.offline import discovery_checkpoints as checkpoints
from deadlock_build_sync.offline.contrast_features import (
    build_feature_matrix as _build_feature_matrix,
)
from deadlock_build_sync.offline.doubly_robust_estimation import (
    _calculate_maximum_weighted_standardized_difference,
    estimate_cross_fitted_doubly_robust_contrast,
)
from deadlock_build_sync.value_validation import (
    require_object_dict,
    require_object_rows,
)
from tests.offline.production_evidence_fixtures import make_contrast_rows
from tests.offline.sql_fixtures import load_fixture_sql
from tests.offline.test_contrast_arrays import add_reference_context_features
from tests.purchase_guidance_fixtures import make_purchase_guidance

if TYPE_CHECKING:
    import pytest

    from deadlock_build_sync.offline.discovery_types import NominatedCoreBuild
    from deadlock_build_sync.offline.doubly_robust_estimation import (
        DoublyRobustContrast,
    )


def nominee() -> NominatedCoreBuild:
    return {
        "items": [2, 3, 4, 5],
        "guide": {
            "ready": True,
            "path": [1, 3, 2, 4, 5],
            "purchase_timing": {
                "items": [
                    {
                        "item_id": 7,
                        "buyers": 100,
                        "counts_by_checkpoint": [0, 0, 30, 0, 0, 0],
                    }
                ]
            },
        },
    }


def decisions() -> list[dict[str, object]]:
    return [
        {
            **row,
            "item_id": 7 if row["item_id"] == 10 else 2,
            "relative_wealth": 0.8,
            "enemy_heroes": [42],
            "enemy_items": [8],
            "owned_before": [1, 3],
        }
        for row in make_contrast_rows(positive=True)
        if row["fold"] != "test"
    ]


def test_choice_cohort_uses_current_inventory_and_all_context_conditions() -> None:
    _, graph = make_purchase_guidance()
    rows = decisions()
    candidates = branches.freeze_branch_candidates(rows, nominee(), graph)
    assert {(row["condition"], row["value"]) for row in candidates} == {
        ("relative_wealth", "behind"),
        ("enemy_hero", 42),
        ("enemy_item", 8),
    }
    assert branches.extract_branch_conditions({"relative_wealth": 1.2}) == {
        ("relative_wealth", "ahead")
    }
    assert branches.extract_branch_conditions({"relative_wealth": 1.0}) == {
        ("relative_wealth", "even")
    }
    assert not branches.is_purchase_legal_at_checkpoint(
        {"owned_before": [2, 3, 4, 5]}, nominee(), 7, 2, graph
    )
    assert not branches.is_purchase_legal_at_checkpoint(
        {"owned_before": [1, 3, 7]}, nominee(), 7, 2, graph
    )
    assert not branches.freeze_branch_candidates(
        rows, {"guide": {"ready": False}}, graph
    )
    assert checkpoints.reconstruct_inventory_before(
        [(0, 1, 10, 0), (0, 2, 20, 40), (0, 1, 30, 0), (0, 2, 60, 0)], 50, graph
    ) == (1,)
    assert checkpoints.reconstruct_inventory_before([(0, 1, 50, 0)], 50, graph) == ()


def test_branch_estimator_uses_corrected_predecision_cohorts_without_test_rows() -> (
    None
):
    _, graph = make_purchase_guidance()
    rows = decisions()
    candidate = branches.freeze_branch_candidates(rows, nominee(), graph)[0]
    result = branches.evaluate_branch_candidates(rows, nominee(), [candidate], graph, 3)
    admitted = require_object_rows(result["branches"])
    assert len(admitted) == 1
    assert result["test_evaluated"] is False
    assert admitted[0]["support"] == 800
    assert (
        branches.evaluate_branch_candidates(
            rows[:10], nominee(), [candidate], graph, 3
        )["branches"]
        == []
    )


def test_cached_branch_fits_preserve_conditions_and_hypothesis_corrections() -> None:
    _, graph = make_purchase_guidance()
    rows = decisions()
    candidates = branches.freeze_branch_candidates(rows, nominee(), graph)
    evaluator = branches.BranchCandidateEvaluator(rows, graph, 3)
    with threadpool_limits(limits=1):
        separate = [
            branches.evaluate_branch_candidates(rows, nominee(), [candidate], graph, 3)
            for candidate in candidates
        ]
        result = evaluator.evaluate_candidates(nominee(), candidates)
        assert result["audit"] == [
            row for report in separate for row in require_object_rows(report["audit"])
        ]
        assert result["branches"] == [
            row
            for report in separate
            for row in require_object_rows(report["branches"])
        ]
        evaluator.hypotheses = 300
        corrected = evaluator.evaluate_candidates(nominee(), candidates)
        assert corrected == branches.evaluate_branch_candidates(
            rows, nominee(), candidates, graph, 300
        )
    assert evaluator.contrast_cache.calculated_fits == 1
    assert evaluator.contrast_cache.reused_fits == 5
    assert all(
        require_object_dict(row["evidence"])["hypotheses"] == 300
        for row in require_object_rows(corrected["audit"])
    )


def test_missing_optional_observations_disable_affected_automatic_choices() -> None:
    _, graph = make_purchase_guidance()
    rows = decisions()
    without_economy = [{**row, "relative_wealth": None} for row in rows]
    assert not branches.freeze_branch_candidates(without_economy, nominee(), graph)
    without_enemies = [{**row, "enemy_heroes": [], "enemy_items": []} for row in rows]
    candidates = branches.freeze_branch_candidates(without_enemies, nominee(), graph)
    assert {row["condition"] for row in candidates} == {"relative_wealth"}


def test_branch_support_counts_each_action_and_discovery_condition_once() -> None:
    _, graph = make_purchase_guidance()
    base = decisions()[0]
    rows = [
        {
            **base,
            "fold": fold,
            "item_id": item,
            "enemy_heroes": [42, 42],
            "enemy_items": [8, 8],
        }
        for fold, item, count in (
            ("train", 7, 20),
            ("train", 2, 19),
            ("validation", 2, 100),
        )
        for _ in range(count)
    ]
    assert not branches.freeze_branch_candidates(rows, nominee(), graph)
    rows.append({**base, "fold": "train", "item_id": 2})
    candidates = branches.freeze_branch_candidates(rows, nominee(), graph)
    assert [(row["condition"], row["value"]) for row in candidates] == [
        ("enemy_hero", 42),
        ("enemy_item", 8),
        ("relative_wealth", "behind"),
    ]


def test_failed_branch_estimation_keeps_manual_choices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, graph = make_purchase_guidance()
    rows = decisions()
    candidate = branches.freeze_branch_candidates(rows, nominee(), graph)[0]

    def fail(*_args: object, **_kwargs: object) -> DoublyRobustContrast:
        raise ValueError("No comparison overlap")

    monkeypatch.setattr(branches, "estimate_admissible_contrast", fail)
    result = branches.evaluate_branch_candidates(rows, nominee(), [candidate], graph, 1)
    assert not result["branches"]
    assert "No comparison overlap" in str(result["audit"])
    assert not branches.is_substitution_legal(
        {"owned_before": []}, {"substitution": {"core": [99], "path": [99]}}, graph
    )
    assert branches.replace_nonfinite_values({
        "bad": float("inf"),
        "values": (1, float("nan")),
    }) == {"bad": None, "values": [1, None]}


def test_branch_comparisons_keep_conditions_checkpoints_and_substitutions_separate() -> (
    None
):
    _, graph = make_purchase_guidance()
    base = decisions()[0]
    rows = [
        {**base, "match_id": match, "item_id": item, "enemy_heroes": [enemy]}
        for match, item, enemy in ((1, 7, 42), (2, 2, 43), (3, 7, 43), (4, 2, 42))
    ]
    rows.extend(
        {**base, "match_id": match, "item_id": item, "owned_before": []}
        for match, item in ((5, 7), (6, 1))
    )
    candidate = {
        "item_id": 7,
        "after_step": 2,
        "comparator_item_id": 2,
        "condition": "enemy_hero",
        "value": 42,
    }
    cache: dict[tuple[int, int, int], branches.ChoiceCohort] = {}
    for changes, expected in (
        ({}, [1, 4]),
        ({"value": 43}, [2, 3]),
        ({"after_step": 0, "comparator_item_id": 1}, [5, 6]),
        ({"substitution": {"core": [99], "path": [99]}}, []),
    ):
        frame = branches.build_comparison_frame(
            rows, nominee(), {**candidate, **changes}, graph, cache
        )
        assert frame["match_id"].to_list() == expected


def test_context_indicators_and_constant_group_imbalance_are_checked() -> None:
    frame = add_reference_context_features(pl.DataFrame(decisions()))
    assert "context_enemy_heroes_42" in frame.columns
    assert "context_owned_before_1" in frame.columns
    assert _build_feature_matrix(frame).shape[0] == frame.height
    assert _calculate_maximum_weighted_standardized_difference(
        np.array([[0.0], [0.0], [1.0], [1.0]]), np.array([0, 0, 1, 1]), np.full(4, 0.5)
    ) == float("inf")
    contrast = estimate_cross_fitted_doubly_robust_contrast(
        pl.DataFrame(decisions()), 7, 2
    )
    assert set(contrast.fold_diagnostics) == {"train", "validation"}
    assert not replace(contrast, stable=False).stable


def test_strict_team_snapshot_and_no_future_enemy_item_enter_branch_state() -> None:
    connection = duckdb.connect()
    connection.execute(load_fixture_sql("checkpoints/create_single_partition.sql"))
    connection.execute(load_fixture_sql("checkpoints/create_enemy_composition.sql"))
    connection.execute(load_fixture_sql("checkpoints/create_team_snapshots.sql"))
    connection.execute(load_fixture_sql("checkpoints/insert_team_snapshots.sql"))
    connection.execute(load_fixture_sql("checkpoints/create_hero_appearance.sql"))
    connection.execute(load_fixture_sql("checkpoints/create_purchases.sql"))
    connection.execute(load_fixture_sql("checkpoints/insert_purchase_history.sql"))
    connection.execute(load_fixture_sql("checkpoints/insert_teammate_purchase.sql"))
    assert set(
        checkpoints.load_purchase_event_histories(connection, 12).for_match(1)
    ) == {0, 1}
    assert (
        checkpoints.load_purchase_event_histories(connection, 12, 81, 115).for_match(1)
        == {}
    )
    connection.execute(
        load_fixture_sql("checkpoints/create_decision_opportunities.sql")
    )
    _, graph = make_purchase_guidance()
    row = checkpoints.load_checkpoint_rows(connection, 12, graph)[0]
    assert row["relative_wealth"] == 0.8
    assert row["owned_before"] == [1, 3]
    assert row["enemy_items"] == [7]
    assert row["own_team_net_worth"] == 60000
    connection.execute(load_fixture_sql("checkpoints/remove_enemy_observation.sql"))
    assert (
        checkpoints.load_checkpoint_rows(connection, 12, graph)[0]["relative_wealth"]
        is None
    )
    connection.execute(load_fixture_sql("checkpoints/set_stale_enemy_snapshot.sql"))
    stale = checkpoints.load_checkpoint_rows(connection, 12, graph)[0]
    assert stale["enemy_items"] == []
    assert stale["enemy_heroes"] == []
    connection.close()
