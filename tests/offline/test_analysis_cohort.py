from __future__ import annotations

import duckdb
import polars as pl

from tools.comparisons.legacy.analysis_cohort import (
    _cohort_adoption_stability,
    _cohort_audits,
    _paired_adoption_stability,
    _purchase_state_coverage,
    _sequence_model_evaluation,
)

type _Row = dict[str, object]


def _cohort_rows(
    match_id: int,
    calibration: str,
    badge: int,
    offset: int,
) -> tuple[_Row, list[_Row]]:
    fold = "train" if offset < 10 else "test"
    player: _Row = {
        "match_id": match_id,
        "hero_id": 1,
        "calibration": calibration,
        "won": offset % 2 == 0,
        "final_net_worth": 20_000 + offset * 100,
        "start_time": f"2026-08-{offset % 5 + 1:02d} 00:00:00+00",
        "average_badge": badge,
    }
    purchases: list[_Row] = [
        {
            "match_id": match_id,
            "player_slot": 0,
            "hero_id": 1,
            "tier": 1,
            "item_id": item_id,
            "calibration": calibration,
            "average_badge": badge,
            "phase": index,
            "fold": fold,
            "buy_time": 100 + index * 100,
            "prior_purchase_count": index,
            "own_net_worth_at_buy": None if index == 0 else 5_000 + index * 1_000,
            "team_net_worth_lead": None if index == 0 else 100,
            "own_team_observed_players": 6 if index == 2 else 5,
            "enemy_team_observed_players": 6 if index == 2 else 5,
        }
        for index, item_id in enumerate((10, 11, 12))
    ]
    return player, purchases


def _cohort_connection() -> duckdb.DuckDBPyConnection:
    players: list[dict[str, object]] = []
    purchases: list[dict[str, object]] = []
    match_id = 1
    for calibration, badge in (("calibrated", 75), ("provisional", 85)):
        for offset in range(20):
            player, purchase_rows = _cohort_rows(
                match_id,
                calibration,
                badge,
                offset,
            )
            players.append(player)
            purchases.extend(purchase_rows)
            match_id += 1
    assets = pl.DataFrame({
        "item_id": [10, 11, 12],
        "class_name": ["item_10", "item_11", "item_12"],
        "component_items_json": ["[]", "[]", '["item_11"]'],
    })
    con = duckdb.connect()
    con.register("players_source", pl.DataFrame(players, strict=False))
    con.register("purchases_source", pl.DataFrame(purchases, strict=False))
    con.register("assets_source", assets)
    con.execute("CREATE TABLE player_matches AS SELECT * FROM players_source")
    con.execute("CREATE TABLE first_purchases AS SELECT * FROM purchases_source")
    con.execute("CREATE TABLE item_assets AS SELECT * FROM assets_source")
    return con


def test_cohort_audits_stability_state_and_sequences() -> None:
    con = _cohort_connection()
    try:
        calibration, daily, badges = _cohort_audits(con)
        calibration_stability, rank_stability = _cohort_adoption_stability(con)
        coverage = _purchase_state_coverage(con)
        sequences = _sequence_model_evaluation(con)
    finally:
        con.close()

    assert calibration.height == 2
    assert daily.height == 10
    assert badges.height == 2
    assert calibration_stability.height == 1
    assert rank_stability.height == 1
    assert coverage.height == 3
    assert (
        coverage.filter(pl.col("phase") == 2)["complete_team_snapshot_share"].item()
        == 1.0
    )
    assert sequences.height == 10
    assert set(sequences["model"]) == {
        "first_order_transition",
        "first_item_conditioned_transition",
        "hero_next_item_popularity",
        "hero_phase_next_item_popularity",
        "hero_position_next_item_popularity",
    }


def test_paired_stability_skips_sparse_cells_and_keeps_nan() -> None:
    sparse = pl.DataFrame([
        {
            "hero_id": 1,
            "tier": 1,
            "item_id": item_id,
            "group": group,
            "adoption_rate": float(item_id),
        }
        for group in ("a", "b")
        for item_id in (1, 2)
    ])
    constant = pl.DataFrame([
        {
            "hero_id": 1,
            "tier": 1,
            "item_id": item_id,
            "group": group,
            "adoption_rate": 0.5,
        }
        for group in ("a", "b")
        for item_id in (1, 2, 3)
    ])

    assert _paired_adoption_stability(sparse, "group").is_empty()
    result = _paired_adoption_stability(constant, "group")
    assert result.height == 1
    assert result["spearman"].item() is None
    assert result["top10_jaccard"].item() == 1.0
