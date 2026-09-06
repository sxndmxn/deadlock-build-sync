from __future__ import annotations

import math
from typing import TYPE_CHECKING

import numpy as np
import polars as pl
from scipy.stats import spearmanr
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

if TYPE_CHECKING:
    import duckdb

STATE_FEATURES = (
    "phase",
    "buy_time",
    "average_badge",
    "own_net_worth_at_buy",
    "team_net_worth_lead",
    "prior_catalog_spend",
    "prior_purchase_count",
)
RIDGE_FEATURES = ("item_id", *STATE_FEATURES)


def _matrix(
    frame: pl.DataFrame, features: tuple[str, ...] = RIDGE_FEATURES
) -> np.ndarray:
    columns = []
    for name in features:
        values = frame[name].cast(pl.Float64, strict=False).to_numpy()
        columns.append(values)
    return np.column_stack(columns)


def _ridge_pipeline() -> Pipeline:
    transformer = ColumnTransformer([
        ("item", OneHotEncoder(handle_unknown="ignore"), [0]),
        (
            "numeric",
            Pipeline([
                (
                    "impute",
                    SimpleImputer(strategy="median", add_indicator=True),
                ),
                ("scale", StandardScaler()),
            ]),
            list(range(1, len(RIDGE_FEATURES))),
        ),
    ])
    return Pipeline(
        [
            ("features", transformer),
            ("model", LogisticRegression(C=0.5, max_iter=300, solver="lbfgs")),
        ],
        memory=None,
    )


def _state_only_pipeline() -> Pipeline:
    transformer = ColumnTransformer([
        (
            "numeric",
            Pipeline([
                (
                    "impute",
                    SimpleImputer(strategy="median", add_indicator=True),
                ),
                ("scale", StandardScaler()),
            ]),
            list(range(len(STATE_FEATURES))),
        )
    ])
    return Pipeline(
        [
            ("features", transformer),
            ("model", LogisticRegression(C=0.5, max_iter=300, solver="lbfgs")),
        ],
        memory=None,
    )


def _ridge_group_is_modelable(group: pl.DataFrame) -> bool:
    return (
        group.height >= 200
        and group["won"].n_unique() >= 2
        and group["item_id"].n_unique() >= 2
    )


def _evaluate_ridge_holdout(
    hero_id: int,
    tier: int,
    train: pl.DataFrame,
    test: pl.DataFrame,
) -> tuple[Pipeline | None, list[dict[str, object]]]:
    if train.height < 100 or test.height < 20 or train["won"].n_unique() < 2:
        return None, []
    train_model = _ridge_pipeline()
    train_model.fit(_matrix(train), train["won"].to_numpy())
    probabilities = train_model.predict_proba(_matrix(test))[:, 1]
    evaluation = [
        {
            "hero_id": hero_id,
            "tier": tier,
            "model": "ridge_state_model",
            "observations": test.height,
            "brier": brier_score_loss(test["won"].to_numpy(), probabilities),
            "log_loss": log_loss(test["won"].to_numpy(), probabilities, labels=[0, 1]),
        }
    ]
    state_model = _state_only_pipeline()
    state_model.fit(_matrix(train, STATE_FEATURES), train["won"].to_numpy())
    state_probabilities = state_model.predict_proba(_matrix(test, STATE_FEATURES))[:, 1]
    evaluation.append({
        "hero_id": hero_id,
        "tier": tier,
        "model": "state_only_model",
        "observations": test.height,
        "brier": brier_score_loss(test["won"].to_numpy(), state_probabilities),
        "log_loss": log_loss(
            test["won"].to_numpy(),
            state_probabilities,
            labels=[0, 1],
        ),
    })
    return train_model, evaluation


def _score_ridge_counterfactuals(
    hero_id: int,
    tier: int,
    group: pl.DataFrame,
) -> tuple[list[dict[str, object]], pl.DataFrame]:
    full_model = _ridge_pipeline()
    full_model.fit(_matrix(group), group["won"].to_numpy())
    reference = group.sample(min(3000, group.height), seed=hero_id * 10 + tier)
    scores: list[dict[str, object]] = []
    for item_id in group["item_id"].unique().to_list():
        counterfactual = reference.with_columns(pl.lit(item_id).alias("item_id"))
        adjusted = float(full_model.predict_proba(_matrix(counterfactual))[:, 1].mean())
        scores.append({
            "hero_id": hero_id,
            "tier": tier,
            "item_id": int(item_id),
            "ridge_adjusted_rate": adjusted,
        })
    return scores, reference


def _supported_ridge_items(frame: pl.DataFrame) -> set[int]:
    return set(
        frame.group_by("item_id").len().filter(pl.col("len") >= 20)["item_id"].to_list()
    )


def _ridge_item_values(
    model: Pipeline,
    reference: pl.DataFrame,
    item_ids: list[int],
) -> list[float]:
    values: list[float] = []
    for item_id in item_ids:
        counterfactual = reference.with_columns(pl.lit(item_id).alias("item_id"))
        values.append(float(model.predict_proba(_matrix(counterfactual))[:, 1].mean()))
    return values


def _ridge_split_stability(
    hero_id: int,
    tier: int,
    train: pl.DataFrame,
    test: pl.DataFrame,
    reference: pl.DataFrame,
    train_model: Pipeline | None,
) -> dict[str, object] | None:
    if (
        train_model is None
        or test.height < 100
        or test["won"].n_unique() < 2
        or test["item_id"].n_unique() < 2
    ):
        return None
    test_model = _ridge_pipeline()
    test_model.fit(_matrix(test), test["won"].to_numpy())
    shared_items = sorted(_supported_ridge_items(train) & _supported_ridge_items(test))
    if len(shared_items) < 3:
        return None
    train_values = _ridge_item_values(train_model, reference, shared_items)
    test_values = _ridge_item_values(test_model, reference, shared_items)
    correlation = (
        spearmanr(train_values, test_values).statistic
        if len(set(train_values)) > 1 and len(set(test_values)) > 1
        else None
    )
    train_top = {
        item_id
        for _, item_id in sorted(
            zip(train_values, shared_items, strict=True), reverse=True
        )[:10]
    }
    test_top = {
        item_id
        for _, item_id in sorted(
            zip(test_values, shared_items, strict=True), reverse=True
        )[:10]
    }
    union = train_top | test_top
    return {
        "hero_id": hero_id,
        "tier": tier,
        "method": "ridge_adjusted_rate",
        "shared_items": len(shared_items),
        "spearman": (
            float(correlation)
            if correlation is not None and math.isfinite(correlation)
            else None
        ),
        "top10_jaccard": len(train_top & test_top) / len(union),
    }


def _ridge_scores(
    con: duckdb.DuckDBPyConnection,
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    frame = con.sql(
        """
        SELECT hero_id, tier, item_id, won::INTEGER AS won, fold,
               phase, buy_time, average_badge,
               own_net_worth_at_buy, team_net_worth_lead,
               coalesce(prior_catalog_spend, 0) AS prior_catalog_spend,
               prior_purchase_count
        FROM decision_opportunities
        """
    ).pl()
    scores: list[dict[str, object]] = []
    evaluation: list[dict[str, object]] = []
    stability: list[dict[str, object]] = []
    grouped = frame.group_by(["hero_id", "tier"], maintain_order=True)
    for group_index, (key, group) in enumerate(grouped, start=1):
        hero_id, tier = int(key[0]), int(key[1])
        if not _ridge_group_is_modelable(group):
            continue
        train = group.filter(pl.col("fold") == "train")
        test = group.filter(pl.col("fold") == "test")
        train_model, holdout_evaluation = _evaluate_ridge_holdout(
            hero_id, tier, train, test
        )
        evaluation.extend(holdout_evaluation)
        group_scores, reference = _score_ridge_counterfactuals(hero_id, tier, group)
        scores.extend(group_scores)
        stability_row = _ridge_split_stability(
            hero_id, tier, train, test, reference, train_model
        )
        if stability_row is not None:
            stability.append(stability_row)
        if group_index % 25 == 0:
            print(f"State models: {group_index} hero-tier cells", flush=True)
    return pl.DataFrame(scores), pl.DataFrame(evaluation), pl.DataFrame(stability)


def _baseline_evaluation(
    train_metrics: pl.DataFrame, con: duckdb.DuckDBPyConnection
) -> pl.DataFrame:
    test = con.sql(
        """
        SELECT hero_id, tier, item_id, won::INTEGER AS won
        FROM decision_opportunities WHERE fold = 'test'
        """
    ).pl()
    lookup = train_metrics.select(
        "hero_id",
        "tier",
        "item_id",
        "raw_outcome_rate",
        "wilson_lower",
        "eb_mean",
    )
    joined = test.join(lookup, on=["hero_id", "tier", "item_id"], how="inner")
    rows: list[dict[str, object]] = []
    actual = joined["won"].to_numpy()
    for column in ("raw_outcome_rate", "wilson_lower", "eb_mean"):
        predicted = np.clip(joined[column].to_numpy(), 1e-6, 1 - 1e-6)
        rows.append({
            "model": column,
            "observations": len(actual),
            "brier": brier_score_loss(actual, predicted),
            "log_loss": log_loss(actual, predicted, labels=[0, 1]),
        })
    return pl.DataFrame(rows)


def _rank_stability(train: pl.DataFrame, test: pl.DataFrame) -> pl.DataFrame:
    methods = ["adoption_rate", "wilson_lower", "eb_mean", "eb_lower"]
    rows: list[dict[str, object]] = []
    joined = train.join(
        test.select("hero_id", "tier", "item_id", *methods),
        on=["hero_id", "tier", "item_id"],
        suffix="_test",
    )
    for key, group in joined.group_by(["hero_id", "tier"]):
        hero_id, tier = int(key[0]), int(key[1])
        for method in methods:
            if group.height < 3:
                continue
            correlation = spearmanr(
                group[method].to_numpy(), group[f"{method}_test"].to_numpy()
            ).statistic
            train_top = set(
                group.sort(method, descending=True).head(10)["item_id"].to_list()
            )
            test_top = set(
                group
                .sort(f"{method}_test", descending=True)
                .head(10)["item_id"]
                .to_list()
            )
            union = train_top | test_top
            rows.append({
                "hero_id": hero_id,
                "tier": tier,
                "method": method,
                "shared_items": group.height,
                "spearman": float(correlation) if math.isfinite(correlation) else None,
                "top10_jaccard": len(train_top & test_top) / len(union)
                if union
                else 0.0,
            })
    return pl.DataFrame(rows)


def _interval_overlap_ratio(
    first_low: float | None,
    first_high: float | None,
    second_low: float | None,
    second_high: float | None,
) -> float | None:
    if (
        first_low is None
        or first_high is None
        or second_low is None
        or second_high is None
    ):
        return None
    values = (first_low, first_high, second_low, second_high)
    if not all(math.isfinite(value) for value in values):
        return None
    union = max(first_high, second_high) - min(first_low, second_low)
    if union <= 0:
        return 1.0 if first_low == second_low else None
    overlap = max(0.0, min(first_high, second_high) - max(first_low, second_low))
    return overlap / union


def _timing_window_stability(
    full: pl.DataFrame, train: pl.DataFrame, test: pl.DataFrame
) -> pl.DataFrame:
    keys = ["hero_id", "tier", "item_id"]
    candidates = (
        full
        .sort([*keys[:2], "adoption_rate"], descending=[False, False, True])
        .group_by(keys[:2], maintain_order=True)
        .head(10)
        .select(*keys, "item_name", "adoption_rate")
    )
    measures = [
        "adopter_matches",
        "median_buy_time_s",
        "buy_time_q25_s",
        "buy_time_q75_s",
        "median_valid_buy_net_worth",
        "buy_nw_q25",
        "buy_nw_q75",
        "valid_buy_nw_share",
    ]
    train_selected = train.select(
        *keys, *(pl.col(column).alias(f"{column}_train") for column in measures)
    )
    test_selected = test.select(
        *keys, *(pl.col(column).alias(f"{column}_test") for column in measures)
    )
    joined = candidates.join(train_selected, on=keys).join(test_selected, on=keys)
    rows: list[dict[str, object]] = []
    for row in joined.iter_rows(named=True):
        train_nw = row["median_valid_buy_net_worth_train"]
        test_nw = row["median_valid_buy_net_worth_test"]
        rows.append({
            **row,
            "absolute_median_time_shift_s": abs(
                row["median_buy_time_s_train"] - row["median_buy_time_s_test"]
            ),
            "time_iqr_overlap": _interval_overlap_ratio(
                row["buy_time_q25_s_train"],
                row["buy_time_q75_s_train"],
                row["buy_time_q25_s_test"],
                row["buy_time_q75_s_test"],
            ),
            "absolute_median_net_worth_shift": abs(train_nw - test_nw)
            if train_nw is not None and test_nw is not None
            else None,
            "net_worth_iqr_overlap": _interval_overlap_ratio(
                row["buy_nw_q25_train"],
                row["buy_nw_q75_train"],
                row["buy_nw_q25_test"],
                row["buy_nw_q75_test"],
            ),
        })
    return pl.DataFrame(rows)
