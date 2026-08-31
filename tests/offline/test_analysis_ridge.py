from __future__ import annotations

import math

import duckdb
import polars as pl
import pytest

from deadlock_build_sync.offline.analysis_ridge import (
    _baseline_evaluation,
    _evaluate_ridge_holdout,
    _interval_overlap_ratio,
    _matrix,
    _rank_stability,
    _ridge_group_is_modelable,
    _ridge_scores,
    _timing_window_stability,
)


def _decision_rows() -> pl.DataFrame:
    rows: list[dict[str, object]] = [
        {
            "hero_id": 1,
            "tier": 2,
            "item_id": item_id,
            "won": int((offset + item_id) % 3 != 0),
            "fold": fold,
            "phase": offset % 4,
            "buy_time": 500 + offset * 5,
            "average_badge": 80 + offset % 10,
            "own_net_worth_at_buy": (
                None if offset % 11 == 0 else 5_000 + offset * 100
            ),
            "team_net_worth_lead": (None if offset % 13 == 0 else offset * 50 - 1_000),
            "prior_catalog_spend": offset * 100,
            "prior_purchase_count": offset % 8,
        }
        for fold, count in (("train", 60), ("test", 30))
        for item_id in (10, 11, 12, 13)
        for offset in range(count)
    ]
    return pl.DataFrame(rows, strict=False)


def _metrics() -> pl.DataFrame:
    rows = [
        {
            "hero_id": 1,
            "tier": 2,
            "item_id": item_id,
            "item_name": f"Item {item_id}",
            "adopter_matches": 60,
            "adoption_rate": 0.8 - index * 0.1,
            "raw_outcome_rate": 0.55 - index * 0.02,
            "wilson_lower": 0.45 - index * 0.02,
            "eb_mean": 0.53 - index * 0.02,
            "eb_lower": 0.43 - index * 0.02,
            "median_buy_time_s": 700.0 + index * 20,
            "buy_time_q25_s": 650.0 + index * 20,
            "buy_time_q75_s": 750.0 + index * 20,
            "median_valid_buy_net_worth": 8_000.0 + index * 500,
            "buy_nw_q25": 7_000.0 + index * 500,
            "buy_nw_q75": 9_000.0 + index * 500,
            "valid_buy_nw_share": 0.9,
        }
        for index, item_id in enumerate((10, 11, 12, 13))
    ]
    return pl.DataFrame(rows)


def test_ridge_models_score_items_and_holdout_data() -> None:
    decisions = _decision_rows()
    con = duckdb.connect()
    try:
        con.register("decisions", decisions)
        con.execute("CREATE TABLE decision_opportunities AS SELECT * FROM decisions")

        scores, evaluation, stability = _ridge_scores(con)
        baseline = _baseline_evaluation(_metrics(), con)
    finally:
        con.close()

    assert scores.height == 4
    assert set(evaluation["model"]) == {"ridge_state_model", "state_only_model"}
    assert stability["shared_items"].item() == 4
    assert set(baseline["model"]) == {
        "raw_outcome_rate",
        "wilson_lower",
        "eb_mean",
    }


def test_ridge_validation_rejects_small_or_constant_groups() -> None:
    decisions = _decision_rows()
    assert _ridge_group_is_modelable(decisions)
    assert not _ridge_group_is_modelable(decisions.head(10))
    assert not _ridge_group_is_modelable(decisions.with_columns(pl.lit(1).alias("won")))
    assert not _ridge_group_is_modelable(
        decisions.with_columns(pl.lit(10).alias("item_id"))
    )
    model, evaluation = _evaluate_ridge_holdout(
        1,
        2,
        decisions.head(10),
        decisions.tail(10),
    )
    assert model is None
    assert evaluation == []


def test_ranking_and_timing_stability_measure_shared_items() -> None:
    train = _metrics()
    test = train.with_columns(
        (pl.col("median_buy_time_s") + 10).alias("median_buy_time_s"),
        (pl.col("buy_time_q25_s") + 5).alias("buy_time_q25_s"),
        (pl.col("buy_time_q75_s") + 5).alias("buy_time_q75_s"),
        (pl.col("median_valid_buy_net_worth") + 100).alias(
            "median_valid_buy_net_worth"
        ),
        (pl.col("buy_nw_q25") + 50).alias("buy_nw_q25"),
        (pl.col("buy_nw_q75") + 50).alias("buy_nw_q75"),
    )

    stability = _rank_stability(train, test)
    timing = _timing_window_stability(train, train, test)

    assert stability.height == 4
    assert stability["top10_jaccard"].to_list() == [1.0] * 4
    assert timing.height == 4
    assert timing["absolute_median_time_shift_s"].to_list() == [10.0] * 4
    assert timing["absolute_median_net_worth_shift"].to_list() == [100.0] * 4


def test_ridge_helpers_handle_sparse_and_non_finite_values() -> None:
    matrix = _matrix(_decision_rows().head(2))
    assert matrix.shape == (2, 8)
    assert math.isnan(matrix[0, 4])
    assert _rank_stability(_metrics().head(2), _metrics().head(2)).is_empty()
    assert _interval_overlap_ratio(1, 2, math.inf, 4) is None
    assert _interval_overlap_ratio(2, 1, 3, 2) is None
    assert _interval_overlap_ratio(1, 1, 1, 1) == 1.0
    assert _interval_overlap_ratio(1, 2, 2, 3) == 0.0


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("median_valid_buy_net_worth", None),
        ("buy_nw_q25", None),
        ("buy_nw_q75", None),
    ],
)
def test_timing_stability_keeps_missing_net_worth(
    column: str,
    value: None,
) -> None:
    train = _metrics().with_columns(pl.lit(value).cast(pl.Float64).alias(column))
    result = _timing_window_stability(_metrics(), train, _metrics())

    if column == "median_valid_buy_net_worth":
        assert result["absolute_median_net_worth_shift"].null_count() == 4
    else:
        assert result["net_worth_iqr_overlap"].null_count() == 4
