from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import duckdb
import numpy as np
import polars as pl

from deadlock_build_sync.offline import discovery_branches as branches
from deadlock_build_sync.offline.core_policy_dr import (
    _context_features,
    _matrix,
    _weighted_smd,
    cross_fitted_dr_contrast,
)
from deadlock_build_sync.value_validation import require_object_rows
from tests.offline.production_evidence_fixtures import _contrast_rows
from tests.purchase_guidance_fixtures import guidance_fixture

if TYPE_CHECKING:
    import pytest

    from deadlock_build_sync.offline.core_policy_dr import DrContrast
    from deadlock_build_sync.offline.discovery_types import Nomination


def nominee() -> Nomination:
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
        for row in _contrast_rows(positive=True)
        if row["fold"] != "test"
    ]


def test_choice_cohort_uses_current_inventory_and_all_context_conditions() -> None:
    _, graph = guidance_fixture()
    rows = decisions()
    candidates = branches.freeze_candidates(rows, nominee(), graph)
    assert {(row["condition"], row["value"]) for row in candidates} == {
        ("relative_wealth", "behind"),
        ("enemy_hero", 42),
        ("enemy_item", 8),
    }
    assert branches.conditions({"relative_wealth": 1.2}) == {
        ("relative_wealth", "ahead")
    }
    assert branches.conditions({"relative_wealth": 1.0}) == {
        ("relative_wealth", "even")
    }
    assert not branches.legal_at({"owned_before": [2, 3, 4, 5]}, nominee(), 7, 2, graph)
    assert not branches.legal_at({"owned_before": [1, 3, 7]}, nominee(), 7, 2, graph)
    assert not branches.freeze_candidates(rows, {"guide": {"ready": False}}, graph)
    assert branches.inventory_before(
        [(0, 1, 10, 0), (0, 2, 20, 40), (0, 1, 30, 0), (0, 2, 60, 0)], 50, graph
    ) == (1,)
    assert branches.inventory_before([(0, 1, 50, 0)], 50, graph) == ()


def test_branch_estimator_uses_corrected_predecision_cohorts_without_test_rows() -> (
    None
):
    _, graph = guidance_fixture()
    rows = decisions()
    candidate = branches.freeze_candidates(rows, nominee(), graph)[0]
    result = branches.evaluate_candidates(rows, nominee(), [candidate], graph, 3)
    admitted = require_object_rows(result["branches"])
    assert len(admitted) == 1
    assert result["test_evaluated"] is False
    assert admitted[0]["support"] == 800
    assert (
        branches.evaluate_candidates(rows[:10], nominee(), [candidate], graph, 3)[
            "branches"
        ]
        == []
    )


def test_failed_branch_estimation_keeps_manual_choices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, graph = guidance_fixture()
    rows = decisions()
    candidate = branches.freeze_candidates(rows, nominee(), graph)[0]

    def fail(*_args: object) -> DrContrast:
        raise ValueError("No comparison overlap")

    monkeypatch.setattr(branches, "cross_fitted_dr_contrast", fail)
    result = branches.evaluate_candidates(rows, nominee(), [candidate], graph, 1)
    assert not result["branches"]
    assert "No comparison overlap" in str(result["audit"])
    assert not branches.substitution_legal(
        {"owned_before": []}, {"substitution": {"core": [99], "path": [99]}}, graph
    )
    assert branches.finite_values({
        "bad": float("inf"),
        "values": (1, float("nan")),
    }) == {"bad": None, "values": [1, None]}


def test_context_indicators_and_constant_group_imbalance_are_checked() -> None:
    frame = _context_features(pl.DataFrame(decisions()))
    assert "context_enemy_heroes_42" in frame.columns
    assert "context_owned_before_1" in frame.columns
    assert _matrix(frame).shape[0] == frame.height
    assert _weighted_smd(
        np.array([[0.0], [0.0], [1.0], [1.0]]), np.array([0, 0, 1, 1]), np.full(4, 0.5)
    ) == float("inf")
    contrast = cross_fitted_dr_contrast(pl.DataFrame(decisions()), 7, 2)
    assert set(contrast.fold_diagnostics) == {"train", "validation"}
    assert not replace(contrast, stable=False).stable


def test_strict_team_snapshot_and_no_future_enemy_item_enter_branch_state() -> None:
    con = duckdb.connect()
    con.execute(
        "CREATE TABLE discovery_partitions AS SELECT 1 AS match_id, 'discovery' AS partition"
    )
    con.execute(
        "CREATE TABLE compositions AS SELECT 1 AS match_id, 1 AS team_id, [42,43,44,45,46,47] AS hero_ids"
    )
    con.execute(
        "CREATE TABLE team_snapshots(match_id INT,team_id INT,stat_time INT,team_net_worth INT,observed_players INT)"
    )
    con.execute(
        "INSERT INTO team_snapshots VALUES(1,0,590,60000,6),(1,1,590,60000,6),(1,0,600,999999,6)"
    )
    con.execute("CREATE TABLE player_matches AS SELECT 1 AS match_id, 12 AS hero_id")
    con.execute(
        "CREATE TABLE purchases(match_id INT,player_slot INT,team_id INT,item_id INT,buy_time INT,sold_time INT,event_order INT)"
    )
    con.execute(
        "INSERT INTO purchases VALUES(1,0,0,1,100,0,0),(1,0,0,3,200,0,1),(1,1,1,7,500,0,0),(1,1,1,8,595,0,1),(1,1,1,9,600,0,2)"
    )
    con.execute(
        "CREATE TABLE decision_opportunities AS SELECT 1 AS match_id,0 AS player_slot,0 AS team_id,12 AS hero_id,7 AS item_id,600 AS buy_time,590 AS state_observed_at_s,8000 AS own_net_worth_at_buy,999999 AS own_team_net_worth,60000 AS enemy_team_net_worth,6 AS own_team_observed_players,6 AS enemy_team_observed_players,999999 AS team_net_worth_lead"
    )
    _, graph = guidance_fixture()
    row = branches.checkpoint_rows(con, 12, graph)[0]
    assert row["relative_wealth"] == 0.8
    assert row["owned_before"] == [1, 3]
    assert row["enemy_items"] == [7]
    assert row["own_team_net_worth"] == 60000
    con.execute("UPDATE team_snapshots SET observed_players=5 WHERE team_id=1")
    assert branches.checkpoint_rows(con, 12, graph)[0]["relative_wealth"] is None
    con.execute("UPDATE team_snapshots SET stat_time=299 WHERE team_id=1")
    stale = branches.checkpoint_rows(con, 12, graph)[0]
    assert stale["enemy_items"] == []
    assert stale["enemy_heroes"] == []
    con.close()
