from __future__ import annotations

from typing import TYPE_CHECKING

import duckdb
import polars as pl

from deadlock_build_sync.offline.config import RunPaths
from tools.comparisons.legacy.analysis_base import (
    _add_intervals_and_eb,
    _confounding_correlations_for_group,
    _connection,
    _item_aggregates,
    _outcome_confounding_correlations,
    _state_adjusted,
    _state_overlap_diagnostics,
    _write_csv,
)

if TYPE_CHECKING:
    from pathlib import Path

type _Row = dict[str, object]


def _analysis_record(
    match_id: int,
    fold: str,
    item_id: int,
    offset: int,
) -> tuple[_Row, _Row, _Row, _Row, _Row]:
    won = (offset + item_id) % 3 != 0
    own_net_worth = None if offset == 0 else 8_000 + offset * 100
    return (
        {"match_id": match_id, "hero_id": 1},
        {"match_id": match_id, "fold": fold},
        {
            "match_id": match_id,
            "hero_id": 1,
            "item_id": item_id,
            "item_name": f"Item {item_id}",
            "tier": 2,
            "cost": item_id * 100,
            "slot": "weapon",
            "active": False,
            "won": won,
            "buy_time": 600 + offset,
            "own_net_worth_at_buy": own_net_worth,
            "sold_time": 1_200 if offset == 19 else 0,
            "fold": fold,
        },
        {"match_id": match_id, "hero_id": 1, "item_id": item_id},
        {
            "hero_id": 1,
            "tier": 2,
            "item_id": item_id,
            "phase": offset % 2,
            "own_net_worth_at_buy": own_net_worth,
            "team_net_worth_lead": None if offset == 1 else offset * 50,
            "won": won,
        },
    )


def _analysis_connection() -> duckdb.DuckDBPyConnection:
    first_purchases: list[dict[str, object]] = []
    purchases: list[dict[str, object]] = []
    players: list[dict[str, object]] = []
    folds: list[dict[str, object]] = []
    decisions: list[dict[str, object]] = []
    match_id = 1
    for fold in ("train", "test"):
        for item_id in (10, 11, 12, 13):
            for offset in range(20):
                player, match_fold, first_purchase, purchase, decision = (
                    _analysis_record(match_id, fold, item_id, offset)
                )
                players.append(player)
                folds.append(match_fold)
                first_purchases.append(first_purchase)
                purchases.append(purchase)
                decisions.append(decision)
                match_id += 1
    con = duckdb.connect()
    for source, rows, query in (
        (
            "player_matches_source",
            players,
            "CREATE TABLE player_matches AS SELECT * FROM player_matches_source",
        ),
        (
            "match_folds_source",
            folds,
            "CREATE TABLE match_folds AS SELECT * FROM match_folds_source",
        ),
        (
            "first_purchases_source",
            first_purchases,
            "CREATE TABLE first_purchases AS SELECT * FROM first_purchases_source",
        ),
        (
            "purchases_source",
            purchases,
            "CREATE TABLE purchases AS SELECT * FROM purchases_source",
        ),
        (
            "decision_opportunities_source",
            decisions,
            (
                "CREATE TABLE decision_opportunities AS "
                "SELECT * FROM decision_opportunities_source"
            ),
        ),
    ):
        con.register(source, pl.DataFrame(rows, strict=False))
        con.execute(query)
    return con


def _correlation_metrics() -> pl.DataFrame:
    return pl.DataFrame([
        {
            "hero_id": hero_id,
            "tier": tier,
            "item_id": item_id,
            "median_buy_time_s": float(item_id * 10),
            "median_valid_buy_net_worth": float(item_id * 100),
            "adoption_rate": item_id / 10,
            "cost": item_id * 1_000,
            "raw_outcome_rate": 0.4 + item_id / 100,
        }
        for hero_id in (1, 2)
        for tier in (1, 2)
        for item_id in (1, 2, 3, 4)
    ])


def test_item_aggregates_intervals_and_state_adjustment() -> None:
    con = _analysis_connection()
    try:
        full = _item_aggregates(con, None)
        train = _item_aggregates(con, "train")
        adjusted = _state_adjusted(con)
        overlap = _state_overlap_diagnostics(con)
    finally:
        con.close()

    enriched, priors = _add_intervals_and_eb(full)
    assert full.height == 4
    assert full["adopter_matches"].to_list() == [40] * 4
    assert train["adopter_matches"].to_list() == [20] * 4
    assert enriched["wilson_lower"].null_count() == 0
    assert len(priors) == 1
    assert adjusted.height == 4
    assert adjusted.filter(pl.col("state_coverage") > 0).height == 4
    assert overlap.filter(pl.col("effective_support") > 0).height == 4


def test_confounding_correlations_cover_scopes_and_sparse_groups() -> None:
    metrics = _correlation_metrics()

    correlations = _outcome_confounding_correlations(metrics)
    sparse = _confounding_correlations_for_group(
        "sparse",
        {},
        metrics.head(2),
    )
    constant = _confounding_correlations_for_group(
        "constant",
        {},
        metrics.head(3).with_columns(pl.lit(1.0).alias("cost")),
    )

    assert set(correlations["scope"]) == {"within_hero", "within_hero_tier"}
    assert correlations.height == 24
    assert sparse == []
    assert not any(row["feature"] == "cost" for row in constant)


def test_empty_intervals_and_file_helpers(tmp_path: Path) -> None:
    empty, priors = _add_intervals_and_eb(pl.DataFrame())
    assert empty.is_empty()
    assert priors == []

    paths = RunPaths.create(tmp_path, "analysis-base")
    con = _connection(paths)
    con.close()
    frame = pl.DataFrame({"value": [1]})
    target = tmp_path / "nested" / "result.csv"
    _write_csv(frame, target)

    assert target.exists()
