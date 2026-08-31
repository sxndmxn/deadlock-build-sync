from __future__ import annotations

import math
from collections import defaultdict
from pathlib import Path

import duckdb
import polars as pl
from scipy.stats import spearmanr

from deadlock_build_sync.value_validation import (
    integer,
)

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
) -> tuple[pl.DataFrame, list[dict[str, object]]]:
    rows = frame.to_dicts()
    grouped: dict[tuple[int, int], list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        grouped[integer(row["hero_id"]), integer(row["tier"])].append(row)
    priors: list[dict[str, object]] = []
    output: list[dict[str, object]] = []
    pooled_mean = sum(integer(row["wins"]) for row in rows) / max(
        1, sum(integer(row["adopter_matches"]) for row in rows)
    )
    for (hero_id, tier), group in grouped.items():
        prior = fit_beta_prior(
            ((integer(row["wins"]), integer(row["adopter_matches"])) for row in group),
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
            wins = integer(row["wins"])
            observations = integer(row["adopter_matches"])
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
    output: list[dict[str, object]] = []
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


def _confounding_correlations_for_group(
    scope: str,
    identity: dict[str, object],
    group: pl.DataFrame,
) -> list[dict[str, object]]:
    features = (
        "median_buy_time_s",
        "median_valid_buy_net_worth",
        "adoption_rate",
        "cost",
    )
    correlations: list[dict[str, object]] = []
    for feature in features:
        usable = group.drop_nulls([feature, "raw_outcome_rate"])
        if usable.height < 3 or usable[feature].n_unique() < 2:
            continue
        correlation = spearmanr(
            usable[feature].to_numpy(),
            usable["raw_outcome_rate"].to_numpy(),
        ).statistic
        correlations.append({
            "scope": scope,
            **identity,
            "feature": feature,
            "spearman": float(correlation) if math.isfinite(correlation) else None,
        })
    return correlations


def _outcome_confounding_correlations(metrics: pl.DataFrame) -> pl.DataFrame:
    rows: list[dict[str, object]] = []
    scopes: tuple[tuple[str, list[str]], ...] = (
        ("within_hero", ["hero_id"]),
        ("within_hero_tier", ["hero_id", "tier"]),
    )
    for scope, keys in scopes:
        for key, group in metrics.group_by(keys):
            key_values = key if isinstance(key, tuple) else (key,)
            identity = dict(zip(keys, key_values, strict=True))
            rows.extend(_confounding_correlations_for_group(scope, identity, group))
    return pl.DataFrame(rows)
