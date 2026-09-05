"""Check build masks, inventory timing, interaction adjustment, and value tilt."""

from __future__ import annotations

import duckdb
import numpy as np
import pytest
import torch

from experiments.qdfm.actor_ablation import boltzmann
from experiments.qdfm.build_pool import BuildPool
from experiments.qdfm.combo_data import reconstruct_inventories
from experiments.qdfm.combo_stats import bh_adjust, stratified_contrast
from experiments.qdfm.model import masked_probs


def test_build_mask_rejects_a_mixed_basket_and_keeps_components() -> None:
    pool = BuildPool(
        6, "a", "A", (20,), (10, 20), {}, (), frozenset(), frozenset({10, 20})
    )
    result = pool.action_mask([
        {"item_ids": [10]},
        {"item_ids": [20]},
        {"item_ids": [20, 30]},
        {"item_ids": []},
    ])
    assert result.tolist() == [True, True, False, False]


def test_inventory_excludes_future_and_consumed_items_and_handles_rebuy() -> None:
    con = duckdb.connect()
    con.execute(
        "CREATE TABLE landmarks AS SELECT 1 match_id, 0 player_slot, 100 landmark UNION ALL SELECT 2,0,100"
    )
    con.execute("CREATE TABLE upgrades AS SELECT 20 parent, 10 child")
    con.execute(
        "CREATE TABLE hero_events(match_id INTEGER, player_slot INTEGER, item_id INTEGER, buy_time INTEGER, sold_time INTEGER)"
    )
    con.executemany(
        "INSERT INTO hero_events VALUES (?,?,?,?,?)",
        [
            (1, 0, 10, 10, 0),
            (1, 0, 20, 50, 0),
            (1, 0, 30, 100, 0),
            (2, 0, 10, 10, 0),
            (2, 0, 20, 50, 70),
            (2, 0, 10, 80, 0),
        ],
    )
    reconstruct_inventories(con)
    assert con.execute(
        "SELECT match_id, owned_items FROM inventories ORDER BY match_id"
    ).fetchall() == [(1, [20]), (2, [10])]
    con.close()


def test_known_negative_additive_interaction() -> None:
    arm = np.repeat(np.arange(4), 100)
    outcome = np.concatenate([np.arange(100) < wins for wins in (40, 60, 60, 50)])
    result = stratified_contrast(
        (arm & 1) > 0, (arm & 2) > 0, outcome, np.zeros(400, dtype=int)
    )
    assert result["adjusted"]["interaction"]["difference"] == pytest.approx(-0.3)
    assert result["adjusted"]["both_minus_first_only"]["difference"] == pytest.approx(
        -0.1
    )


def test_adjustment_removes_a_known_mixture_difference() -> None:
    # Combo owners are mostly in the low-win stratum; within each stratum all
    # four groups have exactly the same outcome rate. No interaction exists.
    arms, strata, outcomes = [], [], []
    for stratum, ns in enumerate(((100, 100, 100, 900), (900, 900, 900, 100))):
        for arm, n in enumerate(ns):
            arms.extend([arm] * n)
            strata.extend([stratum] * n)
            outcomes.extend(np.arange(n) < n * (0.2 if stratum == 0 else 0.8))
    arm = np.asarray(arms)
    result = stratified_contrast(
        (arm & 1) > 0, (arm & 2) > 0, np.asarray(outcomes), np.asarray(strata)
    )
    assert (
        result["groups"]["both"]["win_rate"]
        < result["groups"]["first_only"]["win_rate"]
    )
    assert result["adjusted"]["interaction"]["difference"] == pytest.approx(
        0, abs=1e-12
    )
    assert result["adjusted"]["both_minus_first_only"]["difference"] == pytest.approx(
        0, abs=1e-12
    )


def test_sparse_overlap_abstains_instead_of_claiming_a_bad_combo() -> None:
    result = stratified_contrast(
        np.ones(100, dtype=bool),
        np.ones(100, dtype=bool),
        np.zeros(100),
        np.zeros(100, dtype=int),
    )
    assert result["adjusted"] is None
    assert result["joint_overlap_share"] == 0


def test_multiple_comparison_adjustment_is_monotone_in_rank() -> None:
    assert bh_adjust([0.04, 0.001, 0.02]) == pytest.approx([0.04, 0.003, 0.03])
    assert bh_adjust([]) == []


def test_direct_value_tilt_preserves_support_and_zero_beta_behavior() -> None:
    logits = torch.tensor([[0.0, 1.0, 99.0]])
    values = torch.tensor([[0.8, 0.2, 1.0]])
    mask = torch.tensor([[True, True, False]])
    behavior = masked_probs(logits, mask)
    torch.testing.assert_close(boltzmann(logits, values, mask, 0), behavior)
    tilted = boltzmann(logits, values, mask, 5)
    expected_ratio = (behavior[0, 0] / behavior[0, 1]) * torch.exp(
        torch.tensor(5 * 0.6)
    )
    torch.testing.assert_close(tilted[0, 0] / tilted[0, 1], expected_ratio)
    assert tilted[0, 2] == 0
