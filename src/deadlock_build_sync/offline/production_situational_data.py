from __future__ import annotations

import math
from typing import TYPE_CHECKING

import polars as pl

from deadlock_build_sync.build_evidence import (
    MAX_COMPARATIVE_INTERVAL_WIDTH,
)
from deadlock_build_sync.value_validation import (
    integer,
    number,
    object_dict,
)

from .config import RunPaths

if TYPE_CHECKING:
    import duckdb

    from .production_situational_types import SituationalEvidence


def _situational_cells(
    con: duckdb.DuckDBPyConnection,
    hero_id: int,
    *,
    selection_only: bool,
) -> pl.DataFrame:
    fold_filter = "AND p.fold IN ('train', 'validation')" if selection_only else ""
    return con.sql(
        f"""
        WITH observed AS (
            SELECT 'whole_enemy_team' AS scope, p.fold, p.hero_id, p.phase,
                   p.tier, p.item_id, unnest(enemy.hero_ids) AS enemy_hero_id, p.won
            FROM decision_opportunities p
            JOIN compositions enemy
              ON p.match_id = enemy.match_id AND (1 - p.team_id) = enemy.team_id
            WHERE p.hero_id = {hero_id} {fold_filter}
            UNION ALL
            SELECT 'same_lane' AS scope, p.fold, p.hero_id, p.phase,
                   p.tier, p.item_id, enemy.hero_id AS enemy_hero_id, p.won
            FROM decision_opportunities p
            JOIN player_matches enemy
              ON p.match_id = enemy.match_id
             AND (1 - p.team_id) = enemy.team_id
             AND p.assigned_lane = enemy.assigned_lane
            WHERE p.hero_id = {hero_id} {fold_filter}
        )
        SELECT scope, fold, hero_id, phase, tier, item_id, enemy_hero_id,
               count(*) AS observations, avg(won::INTEGER) AS outcome_rate
        FROM observed
        GROUP BY ALL
        """
    ).pl()


def _situational_state_overlap(
    con: duckdb.DuckDBPyConnection,
    hero_id: int,
) -> pl.DataFrame:
    return con.sql(
        f"""
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
            WHERE hero_id = {hero_id} AND fold IN ('train', 'validation')
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
               ) AS effective_support
        FROM overlap GROUP BY hero_id, tier, item_id
        """
    ).pl()


def _situational_selection_matchups(
    cells: pl.DataFrame,
    comparator_item_ids: frozenset[int] | None = None,
) -> pl.DataFrame:
    selected = cells.filter(pl.col("observations") >= 20)
    output: list[dict[str, object]] = []
    keys = ("scope", "hero_id", "enemy_hero_id", "phase", "tier")
    for _, group in selected.group_by(keys, maintain_order=True):
        rows = group.sort(
            ["observations", "item_id"], descending=[True, False]
        ).to_dicts()
        for row in rows:
            comparator = next(
                (
                    candidate
                    for candidate in rows
                    if integer(candidate["item_id"]) != integer(row["item_id"])
                    and (
                        comparator_item_ids is None
                        or integer(candidate["item_id"]) in comparator_item_ids
                    )
                ),
                None,
            )
            if comparator is None:
                output.append({
                    **row,
                    "same_opportunity": False,
                    "comparator_item_id": None,
                    "comparison_support": 0,
                    "comparative_interval_low": None,
                    "comparative_interval_high": None,
                })
                continue
            target_n = integer(row["observations"])
            comparator_n = integer(comparator["observations"])
            target_rate = number(row["outcome_rate"])
            comparator_rate = number(comparator["outcome_rate"])
            estimate = target_rate - comparator_rate
            standard_error = math.sqrt(
                target_rate * (1 - target_rate) / target_n
                + comparator_rate * (1 - comparator_rate) / comparator_n
            )
            margin = 1.96 * standard_error
            output.append({
                **row,
                "same_opportunity": True,
                "comparator_item_id": integer(comparator["item_id"]),
                "comparison_support": comparator_n,
                "comparative_interval_low": estimate - margin,
                "comparative_interval_high": estimate + margin,
            })
    return pl.DataFrame(output, infer_schema_length=None)


def _situational_fold_diagnostics(
    cells: pl.DataFrame,
) -> dict[object, dict[str, object]]:
    diagnostics: dict[object, dict[str, object]] = {}
    for row in cells.iter_rows(named=True):
        key = (
            str(row["scope"]),
            integer(row["phase"]),
            integer(row["tier"]),
            integer(row["item_id"]),
            integer(row["enemy_hero_id"]),
        )
        diagnostics.setdefault(key, {})[str(row["fold"])] = {
            "support": integer(row["observations"]),
            "outcome_rate": number(row["outcome_rate"]),
        }
    return diagnostics


def _load_situational_evidence(
    paths: RunPaths,
    hero_id: int,
    con: duckdb.DuckDBPyConnection | None = None,
    comparator_item_ids: frozenset[int] | None = None,
    preloaded: tuple[pl.DataFrame, pl.DataFrame] | None = None,
) -> SituationalEvidence | None:
    matchup_path = paths.tables / "matchup_interactions.csv"
    overlap_path = paths.tables / "state_overlap_diagnostics.csv"
    stability_path = paths.tables / "matchup_temporal_stability.csv"
    if con is None and not overlap_path.is_file():
        return None
    overlap = (
        preloaded[0]
        if preloaded is not None
        else _situational_state_overlap(con, hero_id)
        if con is not None
        else pl.read_csv(overlap_path).filter(pl.col("hero_id") == hero_id)
    )
    overlap_by_item: dict[int, dict[str, object]] = {}
    for row in overlap.iter_rows(named=True):
        overlap_by_item[integer(row["item_id"])] = row
    if con is not None:
        all_cells = (
            preloaded[1]
            if preloaded is not None
            else _situational_cells(con, hero_id, selection_only=False)
        )
        selection_cells = (
            all_cells
            .filter(pl.col("fold").is_in(["train", "validation"]))
            .group_by(["scope", "hero_id", "phase", "tier", "item_id", "enemy_hero_id"])
            .agg(
                pl.col("observations").sum(),
                (
                    (pl.col("outcome_rate") * pl.col("observations")).sum()
                    / pl.col("observations").sum()
                ).alias("outcome_rate"),
            )
        )
        return (
            _situational_selection_matchups(selection_cells, comparator_item_ids),
            overlap_by_item,
            _situational_fold_diagnostics(all_cells),
        )
    if not matchup_path.is_file() or not stability_path.is_file():
        return None
    matchups = pl.read_csv(matchup_path).filter(pl.col("hero_id") == hero_id)
    stability = pl.read_csv(stability_path).filter(pl.col("hero_id") == hero_id)
    stability_by_scope: dict[object, dict[str, object]] = {}
    for row in stability.iter_rows(named=True):
        stability_by_scope[str(row["scope"])] = row
    return matchups, overlap_by_item, stability_by_scope


def _bounded_comparative_interval(
    row: dict[str, object],
) -> tuple[float, float] | None:
    interval_low = row.get("comparative_interval_low")
    interval_high = row.get("comparative_interval_high")
    bounded = (
        isinstance(interval_low, (int, float))
        and isinstance(interval_high, (int, float))
        and math.isfinite(float(interval_low))
        and math.isfinite(float(interval_high))
        and float(interval_low) <= float(interval_high)
        and float(interval_high) - float(interval_low) <= MAX_COMPARATIVE_INTERVAL_WIDTH
    )
    if not bounded:
        return None
    return float(interval_low), float(interval_high)


def _situational_temporal_diagnostic(
    row: dict[str, object],
    fold_cells: dict[object, dict[str, object]],
) -> dict[str, object]:
    scope = str(row["scope"])
    phase = integer(row["phase"])
    tier = integer(row["tier"])
    item_id = integer(row["item_id"])
    comparator_item_id = integer(row.get("comparator_item_id"), default=0)
    enemy_id = integer(row["enemy_hero_id"])
    target = fold_cells.get((scope, phase, tier, item_id, enemy_id))
    comparator = fold_cells.get((scope, phase, tier, comparator_item_id, enemy_id))
    if target is not None and comparator is not None:
        estimates: dict[str, float] = {}
        support: dict[str, dict[str, int]] = {}
        for fold in ("train", "validation", "test"):
            target_fold = object_dict(target.get(fold))
            comparator_fold = object_dict(comparator.get(fold))
            if target_fold is None or comparator_fold is None:
                continue
            estimates[fold] = number(target_fold["outcome_rate"]) - number(
                comparator_fold["outcome_rate"]
            )
            support[fold] = {
                "item": integer(target_fold["support"]),
                "comparator": integer(comparator_fold["support"]),
            }
        selection_available = all(
            fold in estimates and fold in support for fold in ("train", "validation")
        )
        selection_supported = selection_available and all(
            min(support[fold].values()) >= 20 for fold in ("train", "validation")
        )
        selection_positive = selection_available and all(
            estimates[fold] > 0 for fold in ("train", "validation")
        )
        selection_stable = (
            selection_available
            and abs(estimates["train"] - estimates["validation"]) <= 0.05
        )
        test_available = "test" in estimates and "test" in support
        test_supported = test_available and min(support["test"].values()) >= 20
        test_positive = test_available and estimates["test"] > 0
        return {
            "selection_supported": selection_supported,
            "selection_positive": selection_positive,
            "selection_stable": selection_stable,
            "test_supported": test_supported,
            "test_positive": test_positive,
            "fold_comparative_estimates": estimates,
            "fold_support": support,
        }
    fallback = fold_cells.get(scope, {})
    stable = (
        number(fallback.get("spearman") or 0.0) >= 0.3
        and number(fallback.get("sign_agreement") or 0.0) >= 0.6
    )
    return {
        "selection_supported": stable,
        "selection_positive": stable,
        "selection_stable": stable,
        "test_supported": False,
        "test_positive": False,
        "fold_comparative_estimates": {},
        "fold_support": {},
    }
