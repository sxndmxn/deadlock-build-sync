from __future__ import annotations

import math
from typing import TYPE_CHECKING

import numpy as np
import polars as pl
from scipy.stats import spearmanr

from .analysis_base import MIN_MATCHUP_SUPPORT, _with_matchup_residual

if TYPE_CHECKING:
    import duckdb


def _matchups_and_transitions(
    con: duckdb.DuckDBPyConnection,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    whole_team = con.sql(
        f"""
        WITH enemy_comps AS (
            SELECT p.match_id, p.player_slot, p.hero_id, p.phase, p.tier,
                   p.item_id, p.won,
                   unnest(c.hero_ids) AS enemy_hero_id
            FROM decision_opportunities p
            JOIN compositions c
              ON p.match_id = c.match_id AND (1 - p.team_id) = c.team_id
        ), cells AS (
            SELECT hero_id, phase, tier, item_id, enemy_hero_id,
                   count(*) AS observations, sum(won::INTEGER) AS wins,
                   avg(won::INTEGER) AS outcome_rate
            FROM enemy_comps GROUP BY ALL
            HAVING count(*) >= {MIN_MATCHUP_SUPPORT}
        ), baselines AS (
            SELECT hero_id, phase, tier, item_id,
                   count(*) AS total_observations,
                   avg(won::INTEGER) AS item_outcome_rate
            FROM decision_opportunities GROUP BY hero_id, phase, tier, item_id
        )
        SELECT 'whole_enemy_team' AS scope, c.*, b.item_outcome_rate,
               ((c.wins + b.item_outcome_rate * 100.0) / (c.observations + 100.0))
                   - b.item_outcome_rate AS shrunk_interaction_delta
        FROM cells c JOIN baselines b USING (hero_id, phase, tier, item_id)
        """
    ).pl()
    same_lane = con.sql(
        f"""
        WITH cells AS (
            SELECT p.hero_id, p.phase, p.tier, p.item_id,
                   e.hero_id AS enemy_hero_id,
                   count(*) AS observations, sum(p.won::INTEGER) AS wins,
                   avg(p.won::INTEGER) AS outcome_rate
            FROM decision_opportunities p
            JOIN player_matches e
              ON p.match_id = e.match_id
             AND (1 - p.team_id) = e.team_id
             AND p.assigned_lane = e.assigned_lane
            GROUP BY ALL HAVING count(*) >= {MIN_MATCHUP_SUPPORT}
        ), baselines AS (
            SELECT hero_id, phase, tier, item_id,
                   avg(won::INTEGER) AS item_outcome_rate
            FROM decision_opportunities GROUP BY hero_id, phase, tier, item_id
        )
        SELECT 'same_lane' AS scope, c.*, b.item_outcome_rate,
               ((c.wins + b.item_outcome_rate * 100.0) / (c.observations + 100.0))
                   - b.item_outcome_rate AS shrunk_interaction_delta
        FROM cells c JOIN baselines b USING (hero_id, phase, tier, item_id)
        """
    ).pl()
    matchups = pl.concat([whole_team, same_lane], how="vertical_relaxed")
    whole_hero_effects = con.sql(
        """
        WITH enemy_comps AS (
            SELECT p.hero_id, p.phase, p.tier, p.won,
                   unnest(c.hero_ids) AS enemy_hero_id
            FROM decision_opportunities p
            JOIN compositions c
              ON p.match_id = c.match_id AND (1 - p.team_id) = c.team_id
        ), cells AS (
            SELECT hero_id, phase, tier, enemy_hero_id,
                   count(*) AS hero_matchup_observations,
                   sum(won::INTEGER) AS hero_matchup_wins,
                   avg(won::INTEGER) AS hero_matchup_outcome_rate
            FROM enemy_comps GROUP BY ALL
        ), baselines AS (
            SELECT hero_id, phase, tier, avg(won::INTEGER) AS hero_outcome_rate
            FROM decision_opportunities GROUP BY hero_id, phase, tier
        )
        SELECT 'whole_enemy_team' AS scope, c.*, b.hero_outcome_rate,
               ((c.hero_matchup_wins + b.hero_outcome_rate * 100.0)
                   / (c.hero_matchup_observations + 100.0))
                   - b.hero_outcome_rate AS shrunk_matchup_main_delta
        FROM cells c JOIN baselines b USING (hero_id, phase, tier)
        """
    ).pl()
    lane_hero_effects = con.sql(
        """
        WITH cells AS (
            SELECT p.hero_id, p.phase, p.tier, e.hero_id AS enemy_hero_id,
                   count(*) AS hero_matchup_observations,
                   sum(p.won::INTEGER) AS hero_matchup_wins,
                   avg(p.won::INTEGER) AS hero_matchup_outcome_rate
            FROM decision_opportunities p
            JOIN player_matches e
              ON p.match_id = e.match_id
             AND (1 - p.team_id) = e.team_id
             AND p.assigned_lane = e.assigned_lane
            GROUP BY ALL
        ), baselines AS (
            SELECT hero_id, phase, tier, avg(won::INTEGER) AS hero_outcome_rate
            FROM decision_opportunities GROUP BY hero_id, phase, tier
        )
        SELECT 'same_lane' AS scope, c.*, b.hero_outcome_rate,
               ((c.hero_matchup_wins + b.hero_outcome_rate * 100.0)
                   / (c.hero_matchup_observations + 100.0))
                   - b.hero_outcome_rate AS shrunk_matchup_main_delta
        FROM cells c JOIN baselines b USING (hero_id, phase, tier)
        """
    ).pl()
    hero_effects = pl.concat(
        [whole_hero_effects, lane_hero_effects], how="vertical_relaxed"
    )
    matchups = _with_matchup_residual(
        matchups,
        hero_effects,
        join_keys=["scope", "hero_id", "phase", "tier", "enemy_hero_id"],
        item_delta="shrunk_interaction_delta",
        hero_delta="shrunk_matchup_main_delta",
        output="shrunk_item_residual_delta",
    )
    matchups = _add_same_opportunity_comparators(matchups)
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


def _add_same_opportunity_comparators(matchups: pl.DataFrame) -> pl.DataFrame:
    """Compare each item with the most observed alternative in the same state."""
    keys = ("scope", "hero_id", "enemy_hero_id", "phase", "tier")
    output: list[dict[str, object]] = []
    for _, group in matchups.group_by(keys, maintain_order=True):
        rows = group.sort(
            ["observations", "item_id"], descending=[True, False]
        ).to_dicts()
        for row in rows:
            comparator = next(
                (
                    candidate
                    for candidate in rows
                    if int(candidate["item_id"]) != int(row["item_id"])
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
            estimate = float(row["shrunk_item_residual_delta"]) - float(
                comparator["shrunk_item_residual_delta"]
            )
            target_n = int(row["observations"])
            comparator_n = int(comparator["observations"])
            target_rate = min(1.0, max(0.0, float(row["outcome_rate"])))
            comparator_rate = min(1.0, max(0.0, float(comparator["outcome_rate"])))
            standard_error = math.sqrt(
                target_rate * (1.0 - target_rate) / (target_n + 100.0)
                + comparator_rate * (1.0 - comparator_rate) / (comparator_n + 100.0)
            )
            margin = 1.96 * standard_error
            output.append({
                **row,
                "same_opportunity": True,
                "comparator_item_id": int(comparator["item_id"]),
                "comparison_support": comparator_n,
                "comparative_interval_low": estimate - margin,
                "comparative_interval_high": estimate + margin,
            })
    return pl.DataFrame(output)


def _matchup_temporal_stability(con: duckdb.DuckDBPyConnection) -> pl.DataFrame:
    whole_team = con.sql(
        f"""
        WITH enemy_comps AS (
            SELECT p.fold, p.match_id, p.player_slot, p.hero_id, p.phase,
                   p.tier, p.item_id, p.won,
                   unnest(c.hero_ids) AS enemy_hero_id
            FROM decision_opportunities p
            JOIN compositions c
              ON p.match_id = c.match_id AND (1 - p.team_id) = c.team_id
            WHERE p.fold IN ('train', 'test')
        ), cells AS (
            SELECT fold, hero_id, phase, tier, item_id, enemy_hero_id,
                   count(*) AS observations, sum(won::INTEGER) AS wins
            FROM enemy_comps GROUP BY ALL
            HAVING count(*) >= {MIN_MATCHUP_SUPPORT}
        ), baselines AS (
            SELECT fold, hero_id, phase, tier, item_id,
                   avg(won::INTEGER) AS baseline
            FROM decision_opportunities WHERE fold IN ('train', 'test')
            GROUP BY ALL
        )
        SELECT 'whole_enemy_team' AS scope, c.fold, c.hero_id, c.phase,
               c.tier, c.item_id, c.enemy_hero_id, c.observations,
               ((c.wins + b.baseline * 100.0) / (c.observations + 100.0))
                   - b.baseline AS shrunk_delta
        FROM cells c JOIN baselines b
          USING (fold, hero_id, phase, tier, item_id)
        """
    ).pl()
    same_lane = con.sql(
        f"""
        WITH cells AS (
            SELECT p.fold, p.hero_id, p.phase, p.tier, p.item_id,
                   e.hero_id AS enemy_hero_id,
                   count(*) AS observations, sum(p.won::INTEGER) AS wins
            FROM decision_opportunities p
            JOIN player_matches e
              ON p.match_id = e.match_id
             AND (1 - p.team_id) = e.team_id
             AND p.assigned_lane = e.assigned_lane
            WHERE p.fold IN ('train', 'test')
            GROUP BY ALL HAVING count(*) >= {MIN_MATCHUP_SUPPORT}
        ), baselines AS (
            SELECT fold, hero_id, phase, tier, item_id,
                   avg(won::INTEGER) AS baseline
            FROM decision_opportunities WHERE fold IN ('train', 'test')
            GROUP BY ALL
        )
        SELECT 'same_lane' AS scope, c.fold, c.hero_id, c.phase, c.tier,
               c.item_id, c.enemy_hero_id, c.observations,
               ((c.wins + b.baseline * 100.0) / (c.observations + 100.0))
                   - b.baseline AS shrunk_delta
        FROM cells c JOIN baselines b
          USING (fold, hero_id, phase, tier, item_id)
        """
    ).pl()
    cells = pl.concat([whole_team, same_lane], how="vertical")
    whole_hero_effects = con.sql(
        """
        WITH enemy_comps AS (
            SELECT p.fold, p.hero_id, p.phase, p.tier, p.won,
                   unnest(c.hero_ids) AS enemy_hero_id
            FROM decision_opportunities p
            JOIN compositions c
              ON p.match_id = c.match_id AND (1 - p.team_id) = c.team_id
            WHERE p.fold IN ('train', 'test')
        ), cells AS (
            SELECT fold, hero_id, phase, tier, enemy_hero_id,
                   count(*) AS observations, sum(won::INTEGER) AS wins
            FROM enemy_comps GROUP BY ALL
        ), baselines AS (
            SELECT fold, hero_id, phase, tier, avg(won::INTEGER) AS baseline
            FROM decision_opportunities WHERE fold IN ('train', 'test')
            GROUP BY ALL
        )
        SELECT 'whole_enemy_team' AS scope, c.fold, c.hero_id, c.phase,
               c.tier, c.enemy_hero_id,
               ((c.wins + b.baseline * 100.0) / (c.observations + 100.0))
                   - b.baseline AS matchup_main_delta
        FROM cells c JOIN baselines b USING (fold, hero_id, phase, tier)
        """
    ).pl()
    lane_hero_effects = con.sql(
        """
        WITH cells AS (
            SELECT p.fold, p.hero_id, p.phase, p.tier,
                   e.hero_id AS enemy_hero_id,
                   count(*) AS observations, sum(p.won::INTEGER) AS wins
            FROM decision_opportunities p
            JOIN player_matches e
              ON p.match_id = e.match_id
             AND (1 - p.team_id) = e.team_id
             AND p.assigned_lane = e.assigned_lane
            WHERE p.fold IN ('train', 'test') GROUP BY ALL
        ), baselines AS (
            SELECT fold, hero_id, phase, tier, avg(won::INTEGER) AS baseline
            FROM decision_opportunities WHERE fold IN ('train', 'test')
            GROUP BY ALL
        )
        SELECT 'same_lane' AS scope, c.fold, c.hero_id, c.phase, c.tier,
               c.enemy_hero_id,
               ((c.wins + b.baseline * 100.0) / (c.observations + 100.0))
                   - b.baseline AS matchup_main_delta
        FROM cells c JOIN baselines b USING (fold, hero_id, phase, tier)
        """
    ).pl()
    hero_effects = pl.concat([whole_hero_effects, lane_hero_effects], how="vertical")
    cells = _with_matchup_residual(
        cells,
        hero_effects,
        join_keys=[
            "scope",
            "fold",
            "hero_id",
            "phase",
            "tier",
            "enemy_hero_id",
        ],
        item_delta="shrunk_delta",
        hero_delta="matchup_main_delta",
        output="residual_delta",
    )
    train = cells.filter(pl.col("fold") == "train").drop("fold")
    test = cells.filter(pl.col("fold") == "test").drop("fold")
    joined = train.join(
        test,
        on=[
            "scope",
            "hero_id",
            "phase",
            "tier",
            "item_id",
            "enemy_hero_id",
        ],
        suffix="_test",
    )
    rows: list[dict[str, object]] = []
    for key, group in joined.group_by(["scope", "hero_id"]):
        if group.height < 3:
            continue
        train_values = group["residual_delta"].to_numpy()
        test_values = group["residual_delta_test"].to_numpy()
        correlation = (
            spearmanr(train_values, test_values).statistic
            if np.unique(train_values).size > 1 and np.unique(test_values).size > 1
            else None
        )
        sign_agreement = group.select(
            (pl.col("residual_delta").sign() == pl.col("residual_delta_test").sign())
            .mean()
            .alias("value")
        ).row(0, named=True)["value"]
        rows.append({
            "scope": str(key[0]),
            "hero_id": int(key[1]),
            "shared_interactions": group.height,
            "spearman": (
                float(correlation)
                if correlation is not None and math.isfinite(correlation)
                else None
            ),
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
