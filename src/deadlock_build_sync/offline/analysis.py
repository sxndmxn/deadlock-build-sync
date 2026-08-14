from __future__ import annotations

import math
from collections import defaultdict
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import polars as pl
from scipy.stats import spearmanr
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from .api import read_json, write_json
from .config import RunPaths
from .models import BetaPrior, beta_posterior, fit_beta_prior, wilson_interval

MIN_ITEM_SUPPORT = 20
MIN_MATCHUP_SUPPORT = 100


def _connection(paths: RunPaths) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(paths.raw / "analysis.duckdb"))


def _write_csv(frame: pl.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.write_csv(path)


def _with_matchup_residual(
    cells: pl.DataFrame,
    hero_effects: pl.DataFrame,
    *,
    join_keys: list[str],
    item_delta: str,
    hero_delta: str,
    output: str,
) -> pl.DataFrame:
    """Remove the hero/enemy main effect from an enemy-conditioned item delta."""
    return cells.join(hero_effects, on=join_keys, how="left").with_columns(
        (pl.col(item_delta) - pl.col(hero_delta)).alias(output)
    )


def _item_aggregates(con: duckdb.DuckDBPyConnection, fold: str | None) -> pl.DataFrame:
    joined_condition = "" if fold is None else f"AND f.fold = '{fold}'"
    direct_condition = "" if fold is None else f"AND p.fold = '{fold}'"
    return con.sql(
        f"""
        WITH hero_totals AS (
            SELECT p.hero_id, count(*) AS hero_player_matches
            FROM player_matches p JOIN match_folds f USING (match_id)
            WHERE true {joined_condition}
            GROUP BY p.hero_id
        ), events AS (
            SELECT p.hero_id, p.item_id, count(*) AS purchase_events
            FROM purchases p JOIN match_folds f USING (match_id)
            WHERE true {joined_condition}
            GROUP BY p.hero_id, p.item_id
        ), items AS (
            SELECT
                p.hero_id, p.item_id, any_value(p.item_name) AS item_name,
                any_value(p.tier) AS tier, any_value(p.cost) AS cost,
                any_value(p.slot) AS slot, any_value(p.active) AS active,
                count(*) AS adopter_matches,
                sum(p.won::INTEGER) AS wins,
                avg(p.won::INTEGER) AS raw_outcome_rate,
                median(p.buy_time) AS median_buy_time_s,
                quantile_cont(p.buy_time, 0.25) AS buy_time_q25_s,
                quantile_cont(p.buy_time, 0.75) AS buy_time_q75_s,
                median(p.own_net_worth_at_buy) AS median_valid_buy_net_worth,
                quantile_cont(p.own_net_worth_at_buy, 0.25) AS buy_nw_q25,
                quantile_cont(p.own_net_worth_at_buy, 0.75) AS buy_nw_q75,
                count(p.own_net_worth_at_buy) / count(*) AS valid_buy_nw_share,
                avg((p.sold_time > 0)::INTEGER) AS sell_event_share,
                median(p.sold_time) FILTER (WHERE p.sold_time > 0) AS median_sell_time_s
            FROM first_purchases p
            WHERE true {direct_condition}
            GROUP BY p.hero_id, p.item_id
            HAVING count(*) >= {MIN_ITEM_SUPPORT}
        )
        SELECT i.*, e.purchase_events, h.hero_player_matches,
               i.adopter_matches / h.hero_player_matches AS adoption_rate,
               e.purchase_events / i.adopter_matches AS event_inflation
        FROM items i
        JOIN events e USING (hero_id, item_id)
        JOIN hero_totals h USING (hero_id)
        """
    ).pl()


def _add_intervals_and_eb(
    frame: pl.DataFrame,
) -> tuple[pl.DataFrame, list[dict[str, Any]]]:
    rows = frame.to_dicts()
    grouped: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[int(row["hero_id"]), int(row["tier"])].append(row)
    priors: list[dict[str, Any]] = []
    output: list[dict[str, Any]] = []
    pooled_mean = sum(int(row["wins"]) for row in rows) / max(
        1, sum(int(row["adopter_matches"]) for row in rows)
    )
    for (hero_id, tier), group in grouped.items():
        prior = fit_beta_prior(
            ((int(row["wins"]), int(row["adopter_matches"])) for row in group),
            fallback_mean=pooled_mean,
            source="hero-tier-marginal-likelihood",
        )
        priors.append({
            "hero_id": hero_id,
            "tier": tier,
            "alpha": prior.alpha,
            "beta": prior.beta,
            "mean": prior.mean,
            "strength": prior.strength,
            "source": prior.source,
        })
        for row in group:
            wins = int(row["wins"])
            observations = int(row["adopter_matches"])
            wilson_low, wilson_high = wilson_interval(wins, observations)
            eb_mean, eb_low, eb_high = beta_posterior(wins, observations, prior)
            output.append({
                **row,
                "wilson_lower": wilson_low,
                "wilson_upper": wilson_high,
                "eb_mean": eb_mean,
                "eb_lower": eb_low,
                "eb_upper": eb_high,
                "eb_prior_strength": prior.strength,
            })
    return pl.DataFrame(output), priors


def _state_adjusted(con: duckdb.DuckDBPyConnection) -> pl.DataFrame:
    cells = con.sql(
        """
        WITH decisions AS (
            SELECT *,
                   CASE WHEN own_net_worth_at_buy IS NULL THEN -1
                        ELSE least(12, floor(own_net_worth_at_buy / 5000))::INTEGER END AS own_nw_band,
                   CASE WHEN team_net_worth_lead IS NULL THEN -99
                        ELSE greatest(-8, least(8, floor(team_net_worth_lead / 5000)))::INTEGER END AS lead_band
            FROM decision_opportunities
        )
        SELECT hero_id, tier, item_id, phase, own_nw_band, lead_band,
               count(*) AS observations, sum(won::INTEGER) AS wins
        FROM decisions GROUP BY ALL
        """
    ).pl()
    references = con.sql(
        """
        WITH decisions AS (
            SELECT *,
                   CASE WHEN own_net_worth_at_buy IS NULL THEN -1
                        ELSE least(12, floor(own_net_worth_at_buy / 5000))::INTEGER END AS own_nw_band,
                   CASE WHEN team_net_worth_lead IS NULL THEN -99
                        ELSE greatest(-8, least(8, floor(team_net_worth_lead / 5000)))::INTEGER END AS lead_band
            FROM decision_opportunities
        )
        SELECT hero_id, tier, phase, own_nw_band, lead_band, count(*) AS reference_n
        FROM decisions GROUP BY ALL
        """
    ).pl()
    overall = cells.group_by(["hero_id", "tier", "item_id"]).agg(
        pl.col("wins").sum(), pl.col("observations").sum()
    )
    priors: dict[tuple[int, int], BetaPrior] = {}
    for key, group in overall.group_by(["hero_id", "tier"]):
        hero_id, tier = int(key[0]), int(key[1])
        priors[hero_id, tier] = fit_beta_prior(
            ((int(row["wins"]), int(row["observations"])) for row in group.to_dicts()),
            source="state-adjusted-hero-tier",
        )
    ref_rows: dict[tuple[int, int], dict[tuple[int, int, int], int]] = defaultdict(dict)
    for row in references.to_dicts():
        group_key = (int(row["hero_id"]), int(row["tier"]))
        state = (int(row["phase"]), int(row["own_nw_band"]), int(row["lead_band"]))
        ref_rows[group_key][state] = int(row["reference_n"])
    cell_rows: dict[
        tuple[int, int, int], dict[tuple[int, int, int], tuple[int, int]]
    ] = defaultdict(dict)
    for row in cells.to_dicts():
        item_key = (int(row["hero_id"]), int(row["tier"]), int(row["item_id"]))
        state = (int(row["phase"]), int(row["own_nw_band"]), int(row["lead_band"]))
        cell_rows[item_key][state] = (int(row["wins"]), int(row["observations"]))
    output: list[dict[str, Any]] = []
    for item_key, item_cells in cell_rows.items():
        hero_id, tier, item_id = item_key
        reference = ref_rows[hero_id, tier]
        denominator = sum(reference.values())
        covered = sum(reference.get(state, 0) for state in item_cells)
        weighted = 0.0
        weight = 0
        prior = priors[hero_id, tier]
        for state, (wins, observations) in item_cells.items():
            state_weight = reference.get(state, 0)
            posterior, _, _ = beta_posterior(wins, observations, prior)
            weighted += state_weight * posterior
            weight += state_weight
        output.append({
            "hero_id": hero_id,
            "tier": tier,
            "item_id": item_id,
            "state_adjusted_eb": weighted / weight if weight else prior.mean,
            "state_coverage": covered / denominator if denominator else 0.0,
        })
    return pl.DataFrame(output)


def _state_overlap_diagnostics(con: duckdb.DuckDBPyConnection) -> pl.DataFrame:
    return con.sql(
        """
        WITH decisions AS (
            SELECT *,
                   CASE WHEN own_net_worth_at_buy IS NULL THEN -1
                        ELSE least(12, floor(own_net_worth_at_buy / 5000))::INTEGER
                   END AS own_nw_band,
                   CASE WHEN team_net_worth_lead IS NULL THEN -99
                        ELSE greatest(
                            -8, least(8, floor(team_net_worth_lead / 5000))
                        )::INTEGER
                   END AS lead_band
            FROM decision_opportunities
        ), reference_states AS (
            SELECT hero_id, tier, phase, own_nw_band, lead_band,
                   count(*) AS reference_observations
            FROM decisions GROUP BY ALL
        ), reference_totals AS (
            SELECT hero_id, tier, sum(reference_observations) AS reference_total
            FROM reference_states GROUP BY ALL
        ), item_states AS (
            SELECT hero_id, tier, item_id, phase, own_nw_band, lead_band,
                   count(*) AS item_observations
            FROM decisions GROUP BY ALL
        ), overlap AS (
            SELECT i.*, r.reference_observations, t.reference_total,
                   sum(r.reference_observations) OVER (
                       PARTITION BY i.hero_id, i.tier, i.item_id
                   ) AS covered_reference
            FROM item_states i
            JOIN reference_states r
              USING (hero_id, tier, phase, own_nw_band, lead_band)
            JOIN reference_totals t USING (hero_id, tier)
        )
        SELECT hero_id, tier, item_id,
               sum(item_observations) AS item_observations,
               any_value(covered_reference) / any_value(reference_total)
                   AS state_coverage,
               1.0 / sum(
                   pow(reference_observations / covered_reference, 2)
                   / item_observations
               ) AS effective_support,
               effective_support / sum(item_observations) AS effective_support_share,
               max(
                   (reference_observations / covered_reference) / item_observations
               ) AS maximum_individual_weight
        FROM overlap GROUP BY hero_id, tier, item_id
        """
    ).pl()


def _outcome_confounding_correlations(metrics: pl.DataFrame) -> pl.DataFrame:
    features = (
        "median_buy_time_s",
        "median_valid_buy_net_worth",
        "adoption_rate",
        "cost",
    )
    rows: list[dict[str, Any]] = []
    scopes: tuple[tuple[str, list[str]], ...] = (
        ("within_hero", ["hero_id"]),
        ("within_hero_tier", ["hero_id", "tier"]),
    )
    for scope, keys in scopes:
        for key, group in metrics.group_by(keys):
            key_values = key if isinstance(key, tuple) else (key,)
            identity = dict(zip(keys, key_values, strict=True))
            for feature in features:
                usable = group.drop_nulls([feature, "raw_outcome_rate"])
                if usable.height < 3 or usable[feature].n_unique() < 2:
                    continue
                correlation = spearmanr(
                    usable[feature].to_numpy(),
                    usable["raw_outcome_rate"].to_numpy(),
                ).statistic
                rows.append({
                    "scope": scope,
                    **identity,
                    "feature": feature,
                    "spearman": float(correlation)
                    if math.isfinite(correlation)
                    else None,
                })
    return pl.DataFrame(rows)


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
    return Pipeline([
        ("features", transformer),
        ("model", LogisticRegression(C=0.5, max_iter=300, solver="lbfgs")),
    ])


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
    return Pipeline([
        ("features", transformer),
        ("model", LogisticRegression(C=0.5, max_iter=300, solver="lbfgs")),
    ])


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
    scores: list[dict[str, Any]] = []
    evaluation: list[dict[str, Any]] = []
    stability: list[dict[str, Any]] = []
    grouped = frame.group_by(["hero_id", "tier"], maintain_order=True)
    for group_index, (key, group) in enumerate(grouped, start=1):
        hero_id, tier = int(key[0]), int(key[1])
        if (
            group.height < 200
            or group["won"].n_unique() < 2
            or group["item_id"].n_unique() < 2
        ):
            continue
        train = group.filter(pl.col("fold") == "train")
        test = group.filter(pl.col("fold") == "test")
        train_model: Pipeline | None = None
        if train.height >= 100 and test.height >= 20 and train["won"].n_unique() >= 2:
            train_model = _ridge_pipeline()
            train_model.fit(_matrix(train), train["won"].to_numpy())
            probabilities = train_model.predict_proba(_matrix(test))[:, 1]
            evaluation.append({
                "hero_id": hero_id,
                "tier": tier,
                "model": "ridge_state_model",
                "observations": test.height,
                "brier": brier_score_loss(test["won"].to_numpy(), probabilities),
                "log_loss": log_loss(
                    test["won"].to_numpy(), probabilities, labels=[0, 1]
                ),
            })
            state_model = _state_only_pipeline()
            state_model.fit(_matrix(train, STATE_FEATURES), train["won"].to_numpy())
            state_probabilities = state_model.predict_proba(
                _matrix(test, STATE_FEATURES)
            )[:, 1]
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
        full_model = _ridge_pipeline()
        full_model.fit(_matrix(group), group["won"].to_numpy())
        reference = group.sample(min(3000, group.height), seed=hero_id * 10 + tier)
        for item_id in group["item_id"].unique().to_list():
            counterfactual = reference.with_columns(pl.lit(item_id).alias("item_id"))
            adjusted = float(
                full_model.predict_proba(_matrix(counterfactual))[:, 1].mean()
            )
            scores.append({
                "hero_id": hero_id,
                "tier": tier,
                "item_id": int(item_id),
                "ridge_adjusted_rate": adjusted,
            })
        if (
            train_model is not None
            and test.height >= 100
            and test["won"].n_unique() >= 2
            and test["item_id"].n_unique() >= 2
        ):
            test_model = _ridge_pipeline()
            test_model.fit(_matrix(test), test["won"].to_numpy())
            train_supported = set(
                train
                .group_by("item_id")
                .len()
                .filter(pl.col("len") >= 20)["item_id"]
                .to_list()
            )
            test_supported = set(
                test
                .group_by("item_id")
                .len()
                .filter(pl.col("len") >= 20)["item_id"]
                .to_list()
            )
            shared_items = sorted(train_supported & test_supported)
            if len(shared_items) >= 3:
                train_values: list[float] = []
                test_values: list[float] = []
                for item_id in shared_items:
                    counterfactual = reference.with_columns(
                        pl.lit(item_id).alias("item_id")
                    )
                    matrix = _matrix(counterfactual)
                    train_values.append(
                        float(train_model.predict_proba(matrix)[:, 1].mean())
                    )
                    test_values.append(
                        float(test_model.predict_proba(matrix)[:, 1].mean())
                    )
                correlation = spearmanr(train_values, test_values).statistic
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
                stability.append({
                    "hero_id": hero_id,
                    "tier": tier,
                    "method": "ridge_adjusted_rate",
                    "shared_items": len(shared_items),
                    "spearman": float(correlation)
                    if math.isfinite(correlation)
                    else None,
                    "top10_jaccard": len(train_top & test_top) / len(union),
                })
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
    rows: list[dict[str, Any]] = []
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
    rows: list[dict[str, Any]] = []
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
    rows: list[dict[str, Any]] = []
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


def _matchups_and_transitions(
    con: duckdb.DuckDBPyConnection,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    whole_team = con.sql(
        f"""
        WITH enemy_comps AS (
            SELECT p.match_id, p.player_slot, p.hero_id, p.item_id, p.won,
                   unnest(c.hero_ids) AS enemy_hero_id
            FROM first_purchases p
            JOIN compositions c
              ON p.match_id = c.match_id AND (1 - p.team_id) = c.team_id
        ), cells AS (
            SELECT hero_id, item_id, enemy_hero_id,
                   count(*) AS observations, sum(won::INTEGER) AS wins,
                   avg(won::INTEGER) AS outcome_rate
            FROM enemy_comps GROUP BY ALL
            HAVING count(*) >= {MIN_MATCHUP_SUPPORT}
        ), baselines AS (
            SELECT hero_id, item_id, count(*) AS total_observations,
                   avg(won::INTEGER) AS item_outcome_rate
            FROM first_purchases GROUP BY hero_id, item_id
        )
        SELECT 'whole_enemy_team' AS scope, c.*, b.item_outcome_rate,
               ((c.wins + b.item_outcome_rate * 100.0) / (c.observations + 100.0))
                   - b.item_outcome_rate AS shrunk_interaction_delta
        FROM cells c JOIN baselines b USING (hero_id, item_id)
        """
    ).pl()
    same_lane = con.sql(
        f"""
        WITH cells AS (
            SELECT p.hero_id, p.item_id, e.hero_id AS enemy_hero_id,
                   count(*) AS observations, sum(p.won::INTEGER) AS wins,
                   avg(p.won::INTEGER) AS outcome_rate
            FROM first_purchases p
            JOIN player_matches e
              ON p.match_id = e.match_id
             AND (1 - p.team_id) = e.team_id
             AND p.assigned_lane = e.assigned_lane
            GROUP BY ALL HAVING count(*) >= {MIN_MATCHUP_SUPPORT}
        ), baselines AS (
            SELECT hero_id, item_id, avg(won::INTEGER) AS item_outcome_rate
            FROM first_purchases GROUP BY hero_id, item_id
        )
        SELECT 'same_lane' AS scope, c.*, b.item_outcome_rate,
               ((c.wins + b.item_outcome_rate * 100.0) / (c.observations + 100.0))
                   - b.item_outcome_rate AS shrunk_interaction_delta
        FROM cells c JOIN baselines b USING (hero_id, item_id)
        """
    ).pl()
    matchups = pl.concat([whole_team, same_lane], how="vertical_relaxed")
    whole_hero_effects = con.sql(
        """
        WITH enemy_comps AS (
            SELECT p.hero_id, p.won, unnest(c.hero_ids) AS enemy_hero_id
            FROM player_matches p
            JOIN compositions c
              ON p.match_id = c.match_id AND (1 - p.team_id) = c.team_id
        ), cells AS (
            SELECT hero_id, enemy_hero_id, count(*) AS hero_matchup_observations,
                   sum(won::INTEGER) AS hero_matchup_wins,
                   avg(won::INTEGER) AS hero_matchup_outcome_rate
            FROM enemy_comps GROUP BY ALL
        ), baselines AS (
            SELECT hero_id, avg(won::INTEGER) AS hero_outcome_rate
            FROM player_matches GROUP BY hero_id
        )
        SELECT 'whole_enemy_team' AS scope, c.*, b.hero_outcome_rate,
               ((c.hero_matchup_wins + b.hero_outcome_rate * 100.0)
                   / (c.hero_matchup_observations + 100.0))
                   - b.hero_outcome_rate AS shrunk_matchup_main_delta
        FROM cells c JOIN baselines b USING (hero_id)
        """
    ).pl()
    lane_hero_effects = con.sql(
        """
        WITH cells AS (
            SELECT p.hero_id, e.hero_id AS enemy_hero_id,
                   count(*) AS hero_matchup_observations,
                   sum(p.won::INTEGER) AS hero_matchup_wins,
                   avg(p.won::INTEGER) AS hero_matchup_outcome_rate
            FROM player_matches p
            JOIN player_matches e
              ON p.match_id = e.match_id
             AND (1 - p.team_id) = e.team_id
             AND p.assigned_lane = e.assigned_lane
            GROUP BY ALL
        ), baselines AS (
            SELECT hero_id, avg(won::INTEGER) AS hero_outcome_rate
            FROM player_matches GROUP BY hero_id
        )
        SELECT 'same_lane' AS scope, c.*, b.hero_outcome_rate,
               ((c.hero_matchup_wins + b.hero_outcome_rate * 100.0)
                   / (c.hero_matchup_observations + 100.0))
                   - b.hero_outcome_rate AS shrunk_matchup_main_delta
        FROM cells c JOIN baselines b USING (hero_id)
        """
    ).pl()
    hero_effects = pl.concat(
        [whole_hero_effects, lane_hero_effects], how="vertical_relaxed"
    )
    matchups = _with_matchup_residual(
        matchups,
        hero_effects,
        join_keys=["scope", "hero_id", "enemy_hero_id"],
        item_delta="shrunk_interaction_delta",
        hero_delta="shrunk_matchup_main_delta",
        output="shrunk_item_residual_delta",
    )
    transitions = con.sql(
        """
        WITH ordered AS (
            SELECT hero_id, match_id, player_slot, item_id AS from_item_id,
                   lead(item_id) OVER (
                       PARTITION BY match_id, player_slot ORDER BY buy_time, item_id
                   ) AS to_item_id,
                   won
            FROM first_purchases
        )
        SELECT hero_id, from_item_id, to_item_id,
               count(*) AS observations, sum(won::INTEGER) AS wins,
               avg(won::INTEGER) AS outcome_rate
        FROM ordered WHERE to_item_id IS NOT NULL
        GROUP BY ALL HAVING count(*) >= 20
        """
    ).pl()
    return matchups, transitions


def _matchup_temporal_stability(con: duckdb.DuckDBPyConnection) -> pl.DataFrame:
    whole_team = con.sql(
        f"""
        WITH enemy_comps AS (
            SELECT p.fold, p.match_id, p.player_slot, p.hero_id, p.item_id, p.won,
                   unnest(c.hero_ids) AS enemy_hero_id
            FROM first_purchases p
            JOIN compositions c
              ON p.match_id = c.match_id AND (1 - p.team_id) = c.team_id
            WHERE p.fold IN ('train', 'test')
        ), cells AS (
            SELECT fold, hero_id, item_id, enemy_hero_id,
                   count(*) AS observations, sum(won::INTEGER) AS wins
            FROM enemy_comps GROUP BY ALL
            HAVING count(*) >= {MIN_MATCHUP_SUPPORT}
        ), baselines AS (
            SELECT fold, hero_id, item_id, avg(won::INTEGER) AS baseline
            FROM first_purchases WHERE fold IN ('train', 'test')
            GROUP BY ALL
        )
        SELECT 'whole_enemy_team' AS scope, c.fold, c.hero_id, c.item_id,
               c.enemy_hero_id, c.observations,
               ((c.wins + b.baseline * 100.0) / (c.observations + 100.0))
                   - b.baseline AS shrunk_delta
        FROM cells c JOIN baselines b USING (fold, hero_id, item_id)
        """
    ).pl()
    same_lane = con.sql(
        f"""
        WITH cells AS (
            SELECT p.fold, p.hero_id, p.item_id, e.hero_id AS enemy_hero_id,
                   count(*) AS observations, sum(p.won::INTEGER) AS wins
            FROM first_purchases p
            JOIN player_matches e
              ON p.match_id = e.match_id
             AND (1 - p.team_id) = e.team_id
             AND p.assigned_lane = e.assigned_lane
            WHERE p.fold IN ('train', 'test')
            GROUP BY ALL HAVING count(*) >= {MIN_MATCHUP_SUPPORT}
        ), baselines AS (
            SELECT fold, hero_id, item_id, avg(won::INTEGER) AS baseline
            FROM first_purchases WHERE fold IN ('train', 'test')
            GROUP BY ALL
        )
        SELECT 'same_lane' AS scope, c.fold, c.hero_id, c.item_id,
               c.enemy_hero_id, c.observations,
               ((c.wins + b.baseline * 100.0) / (c.observations + 100.0))
                   - b.baseline AS shrunk_delta
        FROM cells c JOIN baselines b USING (fold, hero_id, item_id)
        """
    ).pl()
    cells = pl.concat([whole_team, same_lane], how="vertical")
    whole_hero_effects = con.sql(
        """
        WITH enemy_comps AS (
            SELECT f.fold, p.hero_id, p.won,
                   unnest(c.hero_ids) AS enemy_hero_id
            FROM player_matches p
            JOIN match_folds f USING (match_id)
            JOIN compositions c
              ON p.match_id = c.match_id AND (1 - p.team_id) = c.team_id
            WHERE f.fold IN ('train', 'test')
        ), cells AS (
            SELECT fold, hero_id, enemy_hero_id, count(*) AS observations,
                   sum(won::INTEGER) AS wins
            FROM enemy_comps GROUP BY ALL
        ), baselines AS (
            SELECT f.fold, p.hero_id, avg(p.won::INTEGER) AS baseline
            FROM player_matches p JOIN match_folds f USING (match_id)
            WHERE f.fold IN ('train', 'test') GROUP BY ALL
        )
        SELECT 'whole_enemy_team' AS scope, c.fold, c.hero_id, c.enemy_hero_id,
               ((c.wins + b.baseline * 100.0) / (c.observations + 100.0))
                   - b.baseline AS matchup_main_delta
        FROM cells c JOIN baselines b USING (fold, hero_id)
        """
    ).pl()
    lane_hero_effects = con.sql(
        """
        WITH cells AS (
            SELECT f.fold, p.hero_id, e.hero_id AS enemy_hero_id,
                   count(*) AS observations, sum(p.won::INTEGER) AS wins
            FROM player_matches p
            JOIN match_folds f USING (match_id)
            JOIN player_matches e
              ON p.match_id = e.match_id
             AND (1 - p.team_id) = e.team_id
             AND p.assigned_lane = e.assigned_lane
            WHERE f.fold IN ('train', 'test') GROUP BY ALL
        ), baselines AS (
            SELECT f.fold, p.hero_id, avg(p.won::INTEGER) AS baseline
            FROM player_matches p JOIN match_folds f USING (match_id)
            WHERE f.fold IN ('train', 'test') GROUP BY ALL
        )
        SELECT 'same_lane' AS scope, c.fold, c.hero_id, c.enemy_hero_id,
               ((c.wins + b.baseline * 100.0) / (c.observations + 100.0))
                   - b.baseline AS matchup_main_delta
        FROM cells c JOIN baselines b USING (fold, hero_id)
        """
    ).pl()
    hero_effects = pl.concat([whole_hero_effects, lane_hero_effects], how="vertical")
    cells = _with_matchup_residual(
        cells,
        hero_effects,
        join_keys=["scope", "fold", "hero_id", "enemy_hero_id"],
        item_delta="shrunk_delta",
        hero_delta="matchup_main_delta",
        output="residual_delta",
    )
    train = cells.filter(pl.col("fold") == "train").drop("fold")
    test = cells.filter(pl.col("fold") == "test").drop("fold")
    joined = train.join(
        test,
        on=["scope", "hero_id", "item_id", "enemy_hero_id"],
        suffix="_test",
    )
    rows: list[dict[str, Any]] = []
    for key, group in joined.group_by(["scope", "hero_id"]):
        if group.height < 3:
            continue
        correlation = spearmanr(
            group["residual_delta"].to_numpy(),
            group["residual_delta_test"].to_numpy(),
        ).statistic
        sign_agreement = group.select(
            (pl.col("residual_delta").sign() == pl.col("residual_delta_test").sign())
            .mean()
            .alias("value")
        ).row(0, named=True)["value"]
        rows.append({
            "scope": str(key[0]),
            "hero_id": int(key[1]),
            "shared_interactions": group.height,
            "spearman": float(correlation) if math.isfinite(correlation) else None,
            "sign_agreement": sign_agreement,
            "median_absolute_change": float(
                group.select(
                    (pl.col("residual_delta") - pl.col("residual_delta_test"))
                    .abs()
                    .median()
                ).item()
            ),
        })
    return pl.DataFrame(rows)


def _cohort_audits(
    con: duckdb.DuckDBPyConnection,
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    hero_calibration = con.sql(
        """
        SELECT hero_id, calibration, count(*) AS player_matches,
               sum(won::INTEGER) AS wins, avg(won::INTEGER) AS outcome_rate,
               avg(final_net_worth) AS avg_final_net_worth
        FROM player_matches GROUP BY ALL ORDER BY hero_id, calibration
        """
    ).pl()
    daily = con.sql(
        """
        SELECT CAST(start_time AS DATE) AS match_date,
               floor(average_badge / 10)::INTEGER AS rank_tier,
               count(*) AS player_matches,
               count(DISTINCT match_id) AS matches,
               avg(won::INTEGER) AS outcome_rate
        FROM player_matches GROUP BY ALL ORDER BY match_date, rank_tier
        """
    ).pl()
    badges = con.sql(
        """
        SELECT average_badge, count(*) AS player_matches,
               count(DISTINCT match_id) AS matches
        FROM player_matches GROUP BY ALL ORDER BY average_badge
        """
    ).pl()
    return hero_calibration, daily, badges


def _paired_adoption_stability(
    frame: pl.DataFrame, stratum_column: str
) -> pl.DataFrame:
    rows: list[dict[str, Any]] = []
    strata = sorted(frame[stratum_column].unique().to_list())
    for stratum_index, stratum_a in enumerate(strata):
        for stratum_b in strata[stratum_index + 1 :]:
            left = frame.filter(pl.col(stratum_column) == stratum_a).select(
                "hero_id", "tier", "item_id", "adoption_rate"
            )
            right = frame.filter(pl.col(stratum_column) == stratum_b).select(
                "hero_id", "tier", "item_id", "adoption_rate"
            )
            joined = left.join(
                right,
                on=["hero_id", "tier", "item_id"],
                suffix="_comparison",
            )
            for key, group in joined.group_by(["hero_id", "tier"]):
                if group.height < 3:
                    continue
                correlation = spearmanr(
                    group["adoption_rate"].to_numpy(),
                    group["adoption_rate_comparison"].to_numpy(),
                ).statistic
                first_top = set(
                    group
                    .sort("adoption_rate", descending=True)
                    .head(10)["item_id"]
                    .to_list()
                )
                second_top = set(
                    group
                    .sort("adoption_rate_comparison", descending=True)
                    .head(10)["item_id"]
                    .to_list()
                )
                union = first_top | second_top
                rows.append({
                    "hero_id": int(key[0]),
                    "tier": int(key[1]),
                    "stratum_a": str(stratum_a),
                    "stratum_b": str(stratum_b),
                    "shared_items": group.height,
                    "spearman": float(correlation)
                    if math.isfinite(correlation)
                    else None,
                    "top10_jaccard": len(first_top & second_top) / len(union),
                })
    return pl.DataFrame(rows)


def _cohort_adoption_stability(
    con: duckdb.DuckDBPyConnection,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    calibration = con.sql(
        """
        WITH denominators AS (
            SELECT hero_id, calibration, count(*) AS hero_matches
            FROM player_matches GROUP BY ALL
        )
        SELECT f.hero_id, f.tier, f.item_id, f.calibration,
               count(*) AS adopter_matches,
               count(*) / d.hero_matches AS adoption_rate
        FROM first_purchases f
        JOIN denominators d USING (hero_id, calibration)
        GROUP BY f.hero_id, f.tier, f.item_id, f.calibration, d.hero_matches
        HAVING count(*) >= 20
        """
    ).pl()
    ranks = con.sql(
        """
        WITH denominators AS (
            SELECT hero_id, floor(average_badge / 10)::INTEGER AS rank_family,
                   count(*) AS hero_matches
            FROM player_matches GROUP BY ALL
        )
        SELECT f.hero_id, f.tier, f.item_id,
               floor(f.average_badge / 10)::INTEGER AS rank_family,
               count(*) AS adopter_matches,
               count(*) / d.hero_matches AS adoption_rate
        FROM first_purchases f
        JOIN denominators d
          ON f.hero_id = d.hero_id
         AND floor(f.average_badge / 10)::INTEGER = d.rank_family
        GROUP BY f.hero_id, f.tier, f.item_id,
                 floor(f.average_badge / 10)::INTEGER, d.hero_matches
        HAVING count(*) >= 20
        """
    ).pl()
    return (
        _paired_adoption_stability(calibration, "calibration"),
        _paired_adoption_stability(ranks, "rank_family"),
    )


def _purchase_state_coverage(con: duckdb.DuckDBPyConnection) -> pl.DataFrame:
    return con.sql(
        """
        SELECT phase, count(*) AS purchases,
               count(own_net_worth_at_buy) / count(*) AS own_net_worth_share,
               count(team_net_worth_lead) / count(*) AS team_lead_share,
               count(*) FILTER (
                   WHERE own_team_observed_players = 6
                     AND enemy_team_observed_players = 6
               ) / count(*) AS complete_team_snapshot_share,
               count(*) FILTER (
                   WHERE own_team_observed_players = 6
                     AND enemy_team_observed_players = 6
               ) / nullif(count(team_net_worth_lead), 0)
                   AS complete_share_when_lead_present
        FROM first_purchases GROUP BY phase ORDER BY phase
        """
    ).pl()


def _sequence_model_evaluation(con: duckdb.DuckDBPyConnection) -> pl.DataFrame:
    return con.sql(
        """
        WITH component_edges AS (
            SELECT parent.item_id AS to_item_id, child.item_id AS from_item_id
            FROM item_assets parent,
            unnest(from_json(parent.component_items_json, '["VARCHAR"]'))
                AS component(component_class)
            JOIN item_assets child ON child.class_name = component_class
        ), ordered AS (
            SELECT hero_id, fold, phase AS from_phase,
                   prior_purchase_count AS from_position,
                   item_id AS from_item_id,
                   first_value(item_id) OVER (
                       PARTITION BY match_id, player_slot
                       ORDER BY buy_time, item_id
                   ) AS first_item_id,
                   lead(item_id) OVER (
                       PARTITION BY match_id, player_slot
                       ORDER BY buy_time, item_id
                   ) AS to_item_id
            FROM first_purchases
        ), transitions AS (
            SELECT o.*,
                   (c.from_item_id IS NOT NULL)::INTEGER AS is_component_upgrade
            FROM ordered o
            LEFT JOIN component_edges c USING (from_item_id, to_item_id)
            WHERE o.to_item_id IS NOT NULL
        ), train_counts AS (
            SELECT hero_id, from_item_id, to_item_id, count(*) AS observations
            FROM transitions WHERE fold = 'train' GROUP BY ALL
        ), train_first_item_counts AS (
            SELECT hero_id, first_item_id, from_item_id, to_item_id,
                   count(*) AS observations
            FROM transitions WHERE fold = 'train' GROUP BY ALL
        ), train_popularity AS (
            SELECT hero_id, to_item_id, sum(observations) AS observations
            FROM train_counts GROUP BY ALL
        ), train_phase_popularity AS (
            SELECT hero_id, from_phase, to_item_id, count(*) AS observations
            FROM transitions WHERE fold = 'train' GROUP BY ALL
        ), train_position_popularity AS (
            SELECT hero_id, from_position, to_item_id, count(*) AS observations
            FROM transitions WHERE fold = 'train' GROUP BY ALL
        ), popularity_ranks AS (
            SELECT *, row_number() OVER (
                PARTITION BY hero_id
                ORDER BY observations DESC, to_item_id
            ) AS item_rank
            FROM train_popularity
        ), phase_popularity_ranks AS (
            SELECT *, row_number() OVER (
                PARTITION BY hero_id, from_phase
                ORDER BY observations DESC, to_item_id
            ) AS item_rank
            FROM train_phase_popularity
        ), position_popularity_ranks AS (
            SELECT *, row_number() OVER (
                PARTITION BY hero_id, from_position
                ORDER BY observations DESC, to_item_id
            ) AS item_rank
            FROM train_position_popularity
        ), transition_ranks AS (
            SELECT t.*, row_number() OVER (
                PARTITION BY t.hero_id, t.from_item_id
                ORDER BY t.observations DESC, p.item_rank, t.to_item_id
            ) AS item_rank
            FROM train_counts t
            JOIN popularity_ranks p USING (hero_id, to_item_id)
        ), first_item_transition_ranks AS (
            SELECT t.*, row_number() OVER (
                PARTITION BY t.hero_id, t.first_item_id, t.from_item_id
                ORDER BY t.observations DESC, p.item_rank, t.to_item_id
            ) AS item_rank
            FROM train_first_item_counts t
            JOIN popularity_ranks p USING (hero_id, to_item_id)
        ), from_support AS (
            SELECT DISTINCT hero_id, from_item_id FROM train_counts
        ), first_item_from_support AS (
            SELECT DISTINCT hero_id, first_item_id, from_item_id
            FROM train_first_item_counts
        ), test_counts AS (
            SELECT hero_id, from_phase, from_position, first_item_id,
                   from_item_id, to_item_id, is_component_upgrade,
                   count(*) AS observations
            FROM transitions WHERE fold = 'test' GROUP BY ALL
        ), transition_joined AS (
            SELECT q.*, r.item_rank,
                   (s.from_item_id IS NOT NULL)::INTEGER AS context_seen
            FROM test_counts q
            LEFT JOIN transition_ranks r
              USING (hero_id, from_item_id, to_item_id)
            LEFT JOIN from_support s USING (hero_id, from_item_id)
        ), first_item_transition_joined AS (
            SELECT q.*, r.item_rank,
                   (s.from_item_id IS NOT NULL)::INTEGER AS context_seen
            FROM test_counts q
            LEFT JOIN first_item_transition_ranks r
              USING (hero_id, first_item_id, from_item_id, to_item_id)
            LEFT JOIN first_item_from_support s
              USING (hero_id, first_item_id, from_item_id)
        ), popularity_joined AS (
            SELECT q.*, r.item_rank
            FROM test_counts q
            LEFT JOIN popularity_ranks r USING (hero_id, to_item_id)
        ), phase_popularity_joined AS (
            SELECT q.*, r.item_rank
            FROM test_counts q
            LEFT JOIN phase_popularity_ranks r
              USING (hero_id, from_phase, to_item_id)
        ), position_popularity_joined AS (
            SELECT q.*, r.item_rank
            FROM test_counts q
            LEFT JOIN position_popularity_ranks r
              USING (hero_id, from_position, to_item_id)
        ), transition_evaluation AS (
            SELECT 'all' AS evaluation_subset, * FROM transition_joined
            UNION ALL
            SELECT 'non_component' AS evaluation_subset, *
            FROM transition_joined WHERE is_component_upgrade = 0
        ), first_item_transition_evaluation AS (
            SELECT 'all' AS evaluation_subset, *
            FROM first_item_transition_joined
            UNION ALL
            SELECT 'non_component' AS evaluation_subset, *
            FROM first_item_transition_joined WHERE is_component_upgrade = 0
        ), popularity_evaluation AS (
            SELECT 'all' AS evaluation_subset, * FROM popularity_joined
            UNION ALL
            SELECT 'non_component' AS evaluation_subset, *
            FROM popularity_joined WHERE is_component_upgrade = 0
        ), phase_popularity_evaluation AS (
            SELECT 'all' AS evaluation_subset, * FROM phase_popularity_joined
            UNION ALL
            SELECT 'non_component' AS evaluation_subset, *
            FROM phase_popularity_joined WHERE is_component_upgrade = 0
        ), position_popularity_evaluation AS (
            SELECT 'all' AS evaluation_subset, * FROM position_popularity_joined
            UNION ALL
            SELECT 'non_component' AS evaluation_subset, *
            FROM position_popularity_joined WHERE is_component_upgrade = 0
        ), per_hero AS (
            SELECT hero_id, evaluation_subset, 'first_order_transition' AS model,
                   sum(observations) AS test_transitions,
                   sum(observations * context_seen) / sum(observations)
                       AS context_coverage,
                   sum(observations) FILTER (WHERE item_rank IS NOT NULL)
                       / sum(observations) AS target_coverage,
                   sum(observations) FILTER (WHERE item_rank <= 1)
                       / sum(observations) AS top1_accuracy,
                   sum(observations) FILTER (WHERE item_rank <= 3)
                       / sum(observations) AS top3_accuracy,
                   sum(observations) FILTER (WHERE item_rank <= 5)
                       / sum(observations) AS top5_accuracy,
                   sum(observations / item_rank) FILTER (WHERE item_rank IS NOT NULL)
                       / sum(observations) AS mean_reciprocal_rank
            FROM transition_evaluation GROUP BY hero_id, evaluation_subset
            UNION ALL
            SELECT hero_id, evaluation_subset,
                   'first_item_conditioned_transition' AS model,
                   sum(observations) AS test_transitions,
                   sum(observations * context_seen) / sum(observations)
                       AS context_coverage,
                   sum(observations) FILTER (WHERE item_rank IS NOT NULL)
                       / sum(observations) AS target_coverage,
                   sum(observations) FILTER (WHERE item_rank <= 1)
                       / sum(observations) AS top1_accuracy,
                   sum(observations) FILTER (WHERE item_rank <= 3)
                       / sum(observations) AS top3_accuracy,
                   sum(observations) FILTER (WHERE item_rank <= 5)
                       / sum(observations) AS top5_accuracy,
                   sum(observations / item_rank) FILTER (WHERE item_rank IS NOT NULL)
                       / sum(observations) AS mean_reciprocal_rank
            FROM first_item_transition_evaluation
            GROUP BY hero_id, evaluation_subset
            UNION ALL
            SELECT hero_id, evaluation_subset, 'hero_next_item_popularity' AS model,
                   sum(observations) AS test_transitions,
                   1.0 AS context_coverage,
                   sum(observations) FILTER (WHERE item_rank IS NOT NULL)
                       / sum(observations) AS target_coverage,
                   sum(observations) FILTER (WHERE item_rank <= 1)
                       / sum(observations) AS top1_accuracy,
                   sum(observations) FILTER (WHERE item_rank <= 3)
                       / sum(observations) AS top3_accuracy,
                   sum(observations) FILTER (WHERE item_rank <= 5)
                       / sum(observations) AS top5_accuracy,
                   sum(observations / item_rank) FILTER (WHERE item_rank IS NOT NULL)
                       / sum(observations) AS mean_reciprocal_rank
            FROM popularity_evaluation GROUP BY hero_id, evaluation_subset
            UNION ALL
            SELECT hero_id, evaluation_subset,
                   'hero_phase_next_item_popularity' AS model,
                   sum(observations) AS test_transitions,
                   1.0 AS context_coverage,
                   sum(observations) FILTER (WHERE item_rank IS NOT NULL)
                       / sum(observations) AS target_coverage,
                   sum(observations) FILTER (WHERE item_rank <= 1)
                       / sum(observations) AS top1_accuracy,
                   sum(observations) FILTER (WHERE item_rank <= 3)
                       / sum(observations) AS top3_accuracy,
                   sum(observations) FILTER (WHERE item_rank <= 5)
                       / sum(observations) AS top5_accuracy,
                   sum(observations / item_rank) FILTER (WHERE item_rank IS NOT NULL)
                       / sum(observations) AS mean_reciprocal_rank
            FROM phase_popularity_evaluation GROUP BY hero_id, evaluation_subset
            UNION ALL
            SELECT hero_id, evaluation_subset,
                   'hero_position_next_item_popularity' AS model,
                   sum(observations) AS test_transitions,
                   1.0 AS context_coverage,
                   sum(observations) FILTER (WHERE item_rank IS NOT NULL)
                       / sum(observations) AS target_coverage,
                   sum(observations) FILTER (WHERE item_rank <= 1)
                       / sum(observations) AS top1_accuracy,
                   sum(observations) FILTER (WHERE item_rank <= 3)
                       / sum(observations) AS top3_accuracy,
                   sum(observations) FILTER (WHERE item_rank <= 5)
                       / sum(observations) AS top5_accuracy,
                   sum(observations / item_rank) FILTER (WHERE item_rank IS NOT NULL)
                       / sum(observations) AS mean_reciprocal_rank
            FROM position_popularity_evaluation GROUP BY hero_id, evaluation_subset
        )
        SELECT * FROM per_hero ORDER BY evaluation_subset, model, hero_id
        """
    ).pl()


def _duration_profiles(paths: RunPaths) -> pl.DataFrame:
    labels = {
        "under-25m": "<25m",
        "25-30m": "25-30m",
        "30-35m": "30-35m",
        "35-40m": "35-40m",
        "40-45m": "40-45m",
        "45-50m": "45-50m",
        "50m-plus": "50m+",
    }
    rows: list[dict[str, Any]] = []
    for path in sorted(paths.api.glob("hero-duration-*.json")):
        key = path.stem.removeprefix("hero-duration-")
        for row in read_json(path):
            matches = int(row.get("matches") or 0)
            wins = int(row.get("wins") or 0)
            if matches < 20 or not isinstance(row.get("hero_id"), int):
                continue
            rows.append({
                "hero_id": int(row["hero_id"]),
                "duration_bucket": labels.get(key, key),
                "wins": wins,
                "matches": matches,
                "ending_outcome_rate": wins / matches,
            })
    return pl.DataFrame(rows) if rows else pl.DataFrame()


def _match_bootstrap_intervals(metrics: pl.DataFrame) -> pl.DataFrame:
    rng = np.random.default_rng(20260809)
    rows: list[dict[str, Any]] = []
    top = (
        metrics
        .sort(
            ["hero_id", "tier", "adoption_rate"],
            descending=[False, False, True],
        )
        .group_by(["hero_id", "tier"], maintain_order=True)
        .head(10)
    )
    for row in top.to_dicts():
        observations = int(row["adopter_matches"])
        probability = float(row["raw_outcome_rate"])
        # A hero-item has at most one row per match, so resampling match clusters is
        # exactly a binomial resample of these binary outcomes.
        samples = rng.binomial(observations, probability, size=500) / observations
        rows.append({
            "hero_id": int(row["hero_id"]),
            "tier": int(row["tier"]),
            "item_id": int(row["item_id"]),
            "observations": observations,
            "bootstrap_lower": float(np.quantile(samples, 0.025)),
            "bootstrap_median": float(np.quantile(samples, 0.5)),
            "bootstrap_upper": float(np.quantile(samples, 0.975)),
            "bootstrap_replicates": 500,
        })
    return pl.DataFrame(rows)


def _api_audit(
    paths: RunPaths, con: duckdb.DuckDBPyConnection
) -> tuple[pl.DataFrame, pl.DataFrame]:
    raw_events = con.sql(
        """
        SELECT hero_id, item_id, count(*) AS raw_purchase_events,
               count(*) FILTER (WHERE item_purchase_ordinal = 1) AS raw_first_purchase_matches
        FROM purchases GROUP BY hero_id, item_id
        """
    ).pl()
    api_rows: list[dict[str, Any]] = []
    flow_rows: list[dict[str, Any]] = []
    for path in sorted(paths.api.glob("hero-*-item-stats.json")):
        hero_id = int(path.name.split("-")[1])
        for row in read_json(path):
            api_rows.append({
                "hero_id": hero_id,
                "item_id": int(row["item_id"]),
                "api_purchase_events": int(row["matches"]),
                "api_unique_accounts": int(row["players"]),
                "api_outcome_rate": int(row["wins"]) / max(1, int(row["matches"])),
                "api_avg_buy_time_s": row.get("avg_buy_time_s"),
            })
    for path in sorted(paths.api.glob("hero-*-item-flow-stats.json")):
        hero_id = int(path.name.split("-")[1])
        payload = read_json(path)
        for row in payload.get("nodes", []):
            flow_rows.append({
                "hero_id": hero_id,
                "item_id": int(row["item_id"]),
                "phase": int(row["column"]),
                "api_flow_matches": int(row["matches"]),
                "api_flow_player_matches": int(row["players"]),
                "api_adjusted_win_rate": row["adjusted_win_rate"],
                "api_avg_net_worth_at_buy": row["avg_net_worth_at_buy"],
            })
    api_frame = pl.DataFrame(api_rows) if api_rows else pl.DataFrame()
    if not api_frame.is_empty():
        hero_accounts = con.sql(
            "SELECT hero_id, unique_accounts AS hero_unique_accounts "
            "FROM hero_account_counts"
        ).pl()
        api_frame = api_frame.join(
            hero_accounts, on="hero_id", how="left"
        ).with_columns(
            (pl.col("api_unique_accounts") / pl.col("hero_unique_accounts")).alias(
                "api_account_breadth"
            )
        )
    event_audit = (
        raw_events.join(api_frame, on=["hero_id", "item_id"], how="inner")
        if not api_frame.is_empty()
        else raw_events
    )
    flow_frame = pl.DataFrame(flow_rows) if flow_rows else pl.DataFrame()
    raw_flow = con.sql(
        """
        SELECT hero_id, item_id, phase,
               count(*) AS raw_first_purchase_matches,
               avg(own_net_worth_at_buy) AS raw_valid_avg_net_worth_at_buy,
               median(own_net_worth_at_buy) AS raw_valid_median_net_worth_at_buy,
               count(own_net_worth_at_buy) / count(*) AS valid_state_share
        FROM first_purchases GROUP BY ALL
        """
    ).pl()
    flow_audit = (
        raw_flow.join(flow_frame, on=["hero_id", "item_id", "phase"], how="inner")
        if not flow_frame.is_empty()
        else raw_flow
    )
    return event_audit, flow_audit


def _account_breadth_stability(
    metrics: pl.DataFrame, api_events: pl.DataFrame
) -> pl.DataFrame:
    joined = (
        metrics
        .select("hero_id", "tier", "item_id", "adoption_rate")
        .join(
            api_events.select("hero_id", "item_id", "api_account_breadth"),
            on=["hero_id", "item_id"],
            how="inner",
        )
        .drop_nulls()
    )
    rows: list[dict[str, Any]] = []
    for key, group in joined.group_by(["hero_id", "tier"]):
        if group.height < 3:
            continue
        correlation = spearmanr(
            group["adoption_rate"].to_numpy(),
            group["api_account_breadth"].to_numpy(),
        ).statistic
        adoption_top = set(
            group.sort("adoption_rate", descending=True).head(10)["item_id"].to_list()
        )
        breadth_top = set(
            group
            .sort("api_account_breadth", descending=True)
            .head(10)["item_id"]
            .to_list()
        )
        union = adoption_top | breadth_top
        rows.append({
            "hero_id": int(key[0]),
            "tier": int(key[1]),
            "shared_items": group.height,
            "spearman": float(correlation) if math.isfinite(correlation) else None,
            "top10_jaccard": len(adoption_top & breadth_top) / len(union),
        })
    return pl.DataFrame(rows)


def _effective_property_value(prop: dict[str, Any]) -> bool:
    value = prop.get("value")
    if value is None:
        return False
    normalized = str(value).strip().lower()
    return normalized not in {"", "0", "0.0", "-1", "-1.0", "-2", "-2.0", "false"}


def _mechanics_audit(
    paths: RunPaths,
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    items = read_json(paths.raw / "items.json")
    all_assets = read_json(paths.raw / "items-all.json")
    heroes = read_json(paths.raw / "heroes.json")
    by_class = {
        str(asset.get("class_name")): asset
        for asset in all_assets
        if isinstance(asset, dict) and asset.get("class_name")
    }
    item_rows = [
        {
            "item_id": int(item["id"]),
            "item_name": item.get("name"),
            "tier": item.get("item_tier"),
            "slot": item.get("item_slot_type"),
            "cost": item.get("cost"),
            "active": bool(item.get("is_active_item")),
            "has_properties": bool(item.get("properties")),
            "has_components": bool(item.get("component_items")),
            "has_description": bool(item.get("description")),
        }
        for item in items
    ]
    hero_rows: list[dict[str, Any]] = []
    ability_rows: list[dict[str, Any]] = []
    for hero in heroes:
        references = hero.get("items") if isinstance(hero.get("items"), dict) else {}
        abilities = [references.get(f"signature{slot}") for slot in range(1, 5)]
        resolved = [by_class.get(str(class_name), {}) for class_name in abilities]
        active_scaling_count = 0
        for slot, (class_name, ability) in enumerate(
            zip(abilities, resolved, strict=True), start=1
        ):
            properties = ability.get("properties") or {}
            scaled_properties: list[str] = []
            scale_functions: set[str] = set()
            scale_types: set[str] = set()
            spirit_coefficients: list[float] = []
            for property_name, prop in properties.items():
                if not isinstance(prop, dict) or not _effective_property_value(prop):
                    continue
                scale = prop.get("scale_function")
                if not isinstance(scale, dict):
                    continue
                scaled_properties.append(str(property_name))
                class_value = str(scale.get("class_name") or "")
                if class_value:
                    scale_functions.add(class_value)
                specific = scale.get("specific_stat_scale_type")
                if specific:
                    scale_types.add(str(specific))
                scale_types.update(
                    str(stat) for stat in scale.get("scaling_stats") or []
                )
                coefficient = scale.get("stat_scale")
                if "tech_damage" in class_value and isinstance(
                    coefficient, int | float
                ):
                    spirit_coefficients.append(float(coefficient))
            active_scaling_count += bool(scaled_properties)
            description = ability.get("description") or {}
            ability_rows.append({
                "hero_id": int(hero["id"]),
                "hero_name": hero.get("name"),
                "ability_slot": slot,
                "ability_class": class_name,
                "ability_name": ability.get("name"),
                "ability_quip": description.get("quip")
                if isinstance(description, dict)
                else None,
                "scaled_property_count": len(scaled_properties),
                "scaled_properties": " | ".join(sorted(scaled_properties)),
                "scale_functions": " | ".join(sorted(scale_functions)),
                "specific_scale_types": " | ".join(sorted(scale_types)),
                "spirit_damage_coefficients": " | ".join(
                    f"{value:g}" for value in sorted(spirit_coefficients)
                ),
                "has_spirit_damage_scaling": bool(spirit_coefficients),
                "has_duration_scaling": any(
                    "duration" in value.lower()
                    for value in (*scale_functions, *scale_types)
                ),
                "has_range_or_radius_scaling": any(
                    token in value.lower()
                    for value in (*scale_functions, *scale_types)
                    for token in ("range", "radius")
                ),
                "has_cooldown_or_recharge_scaling": any(
                    token in value.lower()
                    for value in (*scale_functions, *scale_types)
                    for token in ("cooldown", "recharge")
                ),
            })
        hero_rows.append({
            "hero_id": int(hero["id"]),
            "hero_name": hero.get("name"),
            "signature_abilities": len([value for value in abilities if value]),
            "resolved_abilities": len([value for value in resolved if value]),
            "abilities_with_scaling": active_scaling_count,
        })
    return (
        pl.DataFrame(item_rows),
        pl.DataFrame(hero_rows),
        pl.DataFrame(ability_rows),
    )


def analyze(paths: RunPaths) -> dict[str, Any]:
    con = _connection(paths)
    try:
        print("Computing item adoption, timing, outcomes, and shrinkage…", flush=True)
        full, full_priors = _add_intervals_and_eb(_item_aggregates(con, None))
        train, train_priors = _add_intervals_and_eb(_item_aggregates(con, "train"))
        test, _ = _add_intervals_and_eb(_item_aggregates(con, "test"))
        state_adjusted = _state_adjusted(con)
        state_overlap = _state_overlap_diagnostics(con)
        confounding_correlations = _outcome_confounding_correlations(full)
        full = full.join(state_adjusted, on=["hero_id", "tier", "item_id"], how="left")

        print("Fitting regularized state-standardization models…", flush=True)
        ridge_scores, ridge_evaluation, ridge_stability = _ridge_scores(con)
        if not ridge_scores.is_empty():
            full = full.join(
                ridge_scores, on=["hero_id", "tier", "item_id"], how="left"
            )

        print("Evaluating temporal stability and source agreement…", flush=True)
        baseline_evaluation = _baseline_evaluation(train, con)
        evaluation = (
            pl.concat([baseline_evaluation, ridge_evaluation], how="diagonal_relaxed")
            if not ridge_evaluation.is_empty()
            else baseline_evaluation
        )
        stability = _rank_stability(train, test)
        timing_stability = _timing_window_stability(full, train, test)
        if not ridge_stability.is_empty():
            stability = pl.concat([stability, ridge_stability], how="vertical")
        matchups, transitions = _matchups_and_transitions(con)
        matchup_stability = _matchup_temporal_stability(con)
        hero_calibration, cohort_daily, cohort_badges = _cohort_audits(con)
        calibration_item_stability, rank_item_stability = _cohort_adoption_stability(
            con
        )
        purchase_state_coverage = _purchase_state_coverage(con)
        sequence_evaluation = _sequence_model_evaluation(con)
        duration_profiles = _duration_profiles(paths)
        bootstrap_intervals = _match_bootstrap_intervals(full)
        api_events, api_flow = _api_audit(paths, con)
        account_breadth_stability = _account_breadth_stability(full, api_events)
        item_mechanics, hero_mechanics, ability_scaling = _mechanics_audit(paths)

        outputs = {
            "item_metrics.csv": full,
            "train_item_metrics.csv": train,
            "test_item_metrics.csv": test,
            "estimator_evaluation.csv": evaluation,
            "state_overlap_diagnostics.csv": state_overlap,
            "outcome_confounding_correlations.csv": confounding_correlations,
            "rank_stability.csv": stability,
            "timing_window_stability.csv": timing_stability,
            "matchup_interactions.csv": matchups,
            "matchup_temporal_stability.csv": matchup_stability,
            "item_transitions.csv": transitions,
            "calibration_sensitivity.csv": hero_calibration,
            "cohort_daily_rank.csv": cohort_daily,
            "cohort_badge_counts.csv": cohort_badges,
            "calibration_item_stability.csv": calibration_item_stability,
            "rank_family_item_stability.csv": rank_item_stability,
            "purchase_state_coverage.csv": purchase_state_coverage,
            "sequence_model_evaluation.csv": sequence_evaluation,
            "hero_duration_profiles.csv": duration_profiles,
            "match_bootstrap_intervals.csv": bootstrap_intervals,
            "api_event_audit.csv": api_events,
            "api_flow_audit.csv": api_flow,
            "account_breadth_stability.csv": account_breadth_stability,
            "item_mechanics_audit.csv": item_mechanics,
            "hero_mechanics_audit.csv": hero_mechanics,
            "hero_ability_scaling.csv": ability_scaling,
        }
        for name, frame in outputs.items():
            _write_csv(frame, paths.tables / name)
        write_json(paths.tables / "full_eb_priors.json", full_priors)
        write_json(paths.tables / "train_eb_priors.json", train_priors)
        return {
            "items": full.height,
            "matchup_cells": matchups.height,
            "matchup_stability_rows": matchup_stability.height,
            "ability_scaling_rows": ability_scaling.height,
            "timing_stability_rows": timing_stability.height,
            "transitions": transitions.height,
            "duration_cells": duration_profiles.height,
            "bootstrap_cells": bootstrap_intervals.height,
            "ridge_scores": ridge_scores.height,
            "evaluation_rows": evaluation.height,
        }
    finally:
        con.close()
