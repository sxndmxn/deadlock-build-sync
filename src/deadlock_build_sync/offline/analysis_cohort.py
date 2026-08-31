from __future__ import annotations

import math
from typing import TYPE_CHECKING

import polars as pl
from scipy.stats import spearmanr

if TYPE_CHECKING:
    import duckdb


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
    rows: list[dict[str, object]] = []
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
