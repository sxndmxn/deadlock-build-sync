import duckdb
import polars as pl
import pytest

from deadlock_build_sync.offline.analysis import (
    _add_same_opportunity_comparators,
    _effective_property_value,
    _interval_overlap_ratio,
    _matchup_temporal_stability,
    _matchups_and_transitions,
    _with_matchup_residual,
)


def test_matchup_residual_subtracts_hero_enemy_main_effect() -> None:
    item_cells = pl.DataFrame({
        "scope": ["same_lane", "same_lane"],
        "hero_id": [1, 1],
        "item_id": [10, 11],
        "enemy_hero_id": [2, 2],
        "shrunk_item_delta": [0.08, -0.02],
    })
    hero_effects = pl.DataFrame({
        "scope": ["same_lane"],
        "hero_id": [1],
        "enemy_hero_id": [2],
        "shrunk_hero_delta": [0.05],
    })

    adjusted = _with_matchup_residual(
        item_cells,
        hero_effects,
        join_keys=["scope", "hero_id", "enemy_hero_id"],
        item_delta="shrunk_item_delta",
        hero_delta="shrunk_hero_delta",
        output="item_residual",
    )

    assert adjusted["item_residual"].to_list() == pytest.approx([0.03, -0.07])


def test_same_opportunity_comparator_is_supported_and_bounded() -> None:
    matchups = pl.DataFrame({
        "scope": ["same_lane", "same_lane", "same_lane"],
        "hero_id": [1, 1, 1],
        "enemy_hero_id": [2, 2, 2],
        "phase": [1, 1, 2],
        "tier": [2, 2, 2],
        "item_id": [10, 11, 12],
        "observations": [400, 300, 500],
        "outcome_rate": [0.60, 0.45, 0.50],
        "shrunk_item_residual_delta": [0.08, -0.03, 0.01],
    })

    compared = _add_same_opportunity_comparators(matchups).sort("item_id")

    first = compared.row(0, named=True)
    assert first["same_opportunity"]
    assert first["comparator_item_id"] == 11
    assert first["comparison_support"] == 300
    assert first["comparative_interval_low"] > 0
    assert first["comparative_interval_high"] > first["comparative_interval_low"]
    unmatched = compared.row(2, named=True)
    assert not unmatched["same_opportunity"]
    assert unmatched["comparator_item_id"] is None


def test_matchup_export_computes_real_same_opportunity_fields() -> None:
    decisions = []
    enemies = []
    compositions = []
    purchases = []
    for item_id in (10, 11, 12):
        for offset in range(200):
            match_id = item_id * 1_000 + offset
            wins_per_fold = {10: 70, 11: 40, 12: 50}[item_id]
            decisions.append({
                "match_id": match_id,
                "player_slot": 0,
                "hero_id": 1,
                "phase": 1,
                "tier": 2,
                "item_id": item_id,
                "won": offset % 100 < wins_per_fold,
                "team_id": 0,
                "assigned_lane": 1,
                "fold": "train" if offset < 100 else "test",
            })
            enemies.append({
                "match_id": match_id,
                "team_id": 1,
                "assigned_lane": 1,
                "hero_id": 2,
            })
            compositions.append({
                "match_id": match_id,
                "team_id": 1,
                "hero_ids": [2],
            })
            purchases.append({
                "hero_id": 1,
                "match_id": match_id,
                "player_slot": 0,
                "item_id": item_id,
                "buy_time": 600,
                "won": offset % 100 < wins_per_fold,
            })
    con = duckdb.connect()
    try:
        con.register("decisions_source", pl.DataFrame(decisions))
        con.register("enemies_source", pl.DataFrame(enemies))
        con.register("compositions_source", pl.DataFrame(compositions))
        con.register("purchases_source", pl.DataFrame(purchases))
        con.execute(
            "CREATE TABLE decision_opportunities AS SELECT * FROM decisions_source"
        )
        con.execute("CREATE TABLE player_matches AS SELECT * FROM enemies_source")
        con.execute("CREATE TABLE compositions AS SELECT * FROM compositions_source")
        con.execute("CREATE TABLE first_purchases AS SELECT * FROM purchases_source")

        matchups, _ = _matchups_and_transitions(con)
        stability = _matchup_temporal_stability(con)
    finally:
        con.close()

    row = (
        matchups
        .filter((pl.col("scope") == "same_lane") & (pl.col("item_id") == 10))
        .select(
            "same_opportunity",
            "comparator_item_id",
            "comparison_support",
            "comparative_interval_low",
            "comparative_interval_high",
        )
        .row(0, named=True)
    )
    assert row["same_opportunity"]
    assert row["comparator_item_id"] == 11
    assert row["comparison_support"] == 200
    assert row["comparative_interval_low"] < row["comparative_interval_high"]
    assert set(stability["scope"]) == {"same_lane", "whole_enemy_team"}


def test_effective_property_value_rejects_engine_sentinels() -> None:
    for value in (None, "", "0", 0, "-1.0", -2, False):
        assert not _effective_property_value({"value": value})
    for value in ("0.5", 1, "12m", True):
        assert _effective_property_value({"value": value})


def test_interval_overlap_ratio_handles_overlap_disjoint_and_points() -> None:
    assert _interval_overlap_ratio(1, 5, 3, 7) == pytest.approx(2 / 6)
    assert _interval_overlap_ratio(1, 2, 3, 4) == 0
    assert _interval_overlap_ratio(2, 2, 2, 2) == 1
    assert _interval_overlap_ratio(None, 2, 1, 2) is None
