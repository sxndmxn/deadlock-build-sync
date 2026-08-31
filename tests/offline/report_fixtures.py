from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl

from deadlock_build_sync.offline.api import write_json
from deadlock_build_sync.offline.config import RunPaths
from deadlock_build_sync.offline.report_types import ReportTables

if TYPE_CHECKING:
    from pathlib import Path


def _frame(rows: list[dict[str, object]]) -> pl.DataFrame:
    return pl.DataFrame(rows, strict=False)


def report_tables() -> ReportTables:
    sequence_specs = [
        ("all", "first_order_transition", 0.30),
        ("non_component", "first_order_transition", 0.25),
        ("all", "first_item_conditioned_transition", 0.40),
        ("non_component", "first_item_conditioned_transition", 0.35),
        ("non_component", "hero_position_next_item_popularity", 0.20),
    ]
    sequence_metrics = [_sequence_metrics(top1) for _, _, top1 in sequence_specs]
    sequence_rows: list[dict[str, object]] = [
        {
            "evaluation_subset": subset,
            "model": model,
            **metrics,
        }
        for (subset, model, _), metrics in zip(
            sequence_specs, sequence_metrics, strict=True
        )
    ]
    rankings = _frame([
        {
            "hero_id": hero_id,
            "tier": 1,
            "item_id": 10 + hero_id,
            "method": method,
            "rank": 1,
            "item_name": f"Item {hero_id}",
            "adoption_rate": 0.6,
            "raw_outcome_rate": 0.55,
        }
        for hero_id in (1, 2)
        for method in (
            "adoption",
            "empirical_bayes_mean",
            "state_adjusted_eb",
            "ridge_adjusted",
        )
    ])
    core_paths = _frame([
        {
            "hero_id": hero_id,
            "method": method,
            "step": step,
            "path_legal": True,
            "path_actions": 8,
            "path_cost": 20_000,
            "final_inventory_items": 7,
            "item_name": f"Item {step}",
        }
        for hero_id in (1, 2)
        for method in ("adoption", "ridge_adjusted")
        for step in (1, 2)
    ])
    return ReportTables(
        manifest={
            "generated_at": "2026-08-30T00:00:00+00:00",
            "cohort": {
                "since": "2026-08-01T00:00:00+00:00",
                "as_of": "2026-08-30T00:00:00+00:00",
            },
            "extraction": {
                "match_folds": 20,
                "player_matches": 40,
                "heroes": 2,
                "purchases": 80,
                "valid_purchase_net_worth": 30,
                "first_purchases": 60,
            },
        },
        heroes={"Abrams": 1, "Haze": 2},
        metrics=_frame([
            {
                "hero_id": hero_id,
                "tier": 1,
                "adoption_rate": rate,
                "event_inflation": 1.0,
            }
            for hero_id, rate in ((1, 0.7), (1, 0.4), (2, 0.6), (2, 0.3))
        ]),
        evaluation=_frame([
            {
                "model": model,
                "observations": 100,
                "brier": brier,
                "log_loss": brier + 0.2,
            }
            for model, brier in (("state_only_model", 0.2), ("ridge_state_model", 0.3))
        ]),
        stability=_frame([
            {"method": "adoption_rate", "spearman": 0.9, "top10_jaccard": 0.8},
            {
                "method": "ridge_adjusted_rate",
                "spearman": 0.4,
                "top10_jaccard": 0.5,
            },
        ]),
        rankings=rankings,
        core_paths=core_paths,
        core_path_stability=_frame([
            {
                "train_legal": True,
                "test_legal": True,
                "item_set_jaccard": 0.8,
                "ordered_lcs_share": 0.7,
                "same_position_share": 0.6,
            },
            {
                "train_legal": True,
                "test_legal": True,
                "item_set_jaccard": 0.6,
                "ordered_lcs_share": 0.5,
                "same_position_share": 0.4,
            },
        ]),
        path_coherence=_frame([
            {
                "player_matches": 10,
                "share_with_six": 0.6,
                "share_with_eight": 0.4,
                "long_matches": 5,
                "long_match_share_with_six": 0.8,
                "long_match_share_with_eight": 0.6,
                "six_item_coherence_lift": 1.2,
                "eight_item_coherence_lift": 1.1,
            },
            {
                "player_matches": 20,
                "share_with_six": 0.5,
                "share_with_eight": 0.3,
                "long_matches": 10,
                "long_match_share_with_six": 0.7,
                "long_match_share_with_eight": 0.5,
                "six_item_coherence_lift": 1.0,
                "eight_item_coherence_lift": 0.9,
            },
        ]),
        path_coherence_temporal=_frame([
            {
                "fold": fold,
                "hero_id": hero_id,
                "hero_name": name,
                "share_with_eight": value,
            }
            for fold, values in (("train", (0.2, 0.7)), ("test", (0.3, 0.6)))
            for (hero_id, name), value in zip(
                ((1, "Abrams"), (2, "Haze")), values, strict=True
            )
        ]),
        api_events=_frame([
            {
                "raw_purchase_events": raw,
                "api_purchase_events": api,
                "api_unique_accounts": accounts,
            }
            for raw, api, accounts in ((100, 102, 70), (200, 198, 120))
        ]),
        account_breadth_stability=_frame([
            {"spearman": 0.9, "top10_jaccard": 0.8},
            {"spearman": 0.8, "top10_jaccard": 0.7},
        ]),
        flow=_flow(),
        mechanics=_frame([
            {
                "hero_name": "Abrams",
                "signature_abilities": 4,
                "resolved_abilities": 4,
                "abilities_with_scaling": 4,
            }
        ]),
        ability_scaling=_frame([
            {
                "hero_id": 1,
                "scaled_property_count": 2,
                "has_spirit_damage_scaling": True,
                "has_duration_scaling": True,
                "has_range_or_radius_scaling": False,
                "has_cooldown_or_recharge_scaling": True,
            },
            {
                "hero_id": 2,
                "scaled_property_count": 0,
                "has_spirit_damage_scaling": False,
                "has_duration_scaling": False,
                "has_range_or_radius_scaling": True,
                "has_cooldown_or_recharge_scaling": False,
            },
        ]),
        matchups=_frame([
            {
                "scope": scope,
                "observations": 100,
                "shrunk_item_residual_delta": delta,
            }
            for scope, delta in (("same_lane", 0.1), ("whole_enemy_team", -0.05))
        ]),
        matchup_stability=_frame([
            {
                "scope": scope,
                "shared_interactions": 10,
                "spearman": value,
                "sign_agreement": 0.8,
                "median_absolute_change": 0.02,
            }
            for scope, value in (("same_lane", 0.5), ("whole_enemy_team", 0.4))
        ]),
        calibration=_frame([
            {"calibration": "calibrated", "player_matches": 30, "wins": 16},
            {"calibration": "provisional", "player_matches": 10, "wins": 4},
        ]),
        cohort_daily=_frame([
            {"match_date": "2026-08-01"},
            {"match_date": "2026-08-30"},
        ]),
        cohort_badges=_frame([
            {"average_badge": 71, "player_matches": 10},
            {"average_badge": 85, "player_matches": 20},
            {"average_badge": 99, "player_matches": 10},
        ]),
        calibration_item_stability=_frame([{"spearman": 0.9, "top10_jaccard": 0.8}]),
        rank_item_stability=_frame([
            {
                "stratum_a": 7,
                "stratum_b": 8,
                "shared_items": 8,
                "spearman": 0.7,
                "top10_jaccard": 0.6,
            }
        ]),
        durations=_frame([
            {
                "duration_bucket": "<25m",
                "wins": 6,
                "matches": 10,
                "ending_outcome_rate": 0.6,
            },
            {
                "duration_bucket": "25-30m",
                "wins": 5,
                "matches": 10,
                "ending_outcome_rate": 0.5,
            },
        ]),
        bootstrap=_frame([
            {
                "bootstrap_lower": 0.4,
                "bootstrap_upper": 0.6,
                "bootstrap_replicates": 100,
            }
        ]),
        state_coverage=_frame([
            {
                "phase": 0,
                "purchases": 100,
                "own_net_worth_share": 0.5,
                "team_lead_share": 0.4,
                "complete_team_snapshot_share": 0.3,
                "complete_share_when_lead_present": 0.7,
            }
        ]),
        timing_stability=_frame([
            {
                "tier": tier,
                "absolute_median_time_shift_s": 20.0,
                "time_iqr_overlap": overlap,
                "absolute_median_net_worth_shift": 100.0,
                "net_worth_iqr_overlap": overlap,
            }
            for tier, overlap in ((1, 0.8), (2, 0.4))
        ]),
        sequence_evaluation=_frame(sequence_rows),
        state_overlap=_frame([
            {
                "hero_id": hero_id,
                "tier": 1,
                "item_id": 10 + hero_id,
                "state_coverage": 0.8,
                "item_observations": 100,
                "effective_support": 60.0,
                "effective_support_share": 0.6,
            }
            for hero_id in (1, 2)
        ]),
        confounding_correlations=_frame([
            {"scope": "all", "feature": "cost", "spearman": 0.2},
            {"scope": "tier", "feature": "cost", "spearman": 0.1},
        ]),
        sequence_all_transition=sequence_metrics[0],
        sequence_non_component_transition=sequence_metrics[1],
        sequence_all_first_item=sequence_metrics[2],
        sequence_non_component_first_item=sequence_metrics[3],
        sequence_non_component_position=sequence_metrics[4],
    )


def _sequence_metrics(top1: float) -> dict[str, int | float]:
    return {
        "test_transitions": 100,
        "context_coverage": 0.9,
        "target_coverage": 0.8,
        "top1_accuracy": top1,
        "top3_accuracy": top1 + 0.2,
        "top5_accuracy": top1 + 0.3,
        "mean_reciprocal_rank": top1 + 0.1,
    }


def _flow() -> pl.DataFrame:
    return _frame([
        {
            "hero_id": 12,
            "item_id": 3_776_945_997,
            "phase": 0,
            "api_avg_net_worth_at_buy": 1_000.0,
            "raw_valid_avg_net_worth_at_buy": 900.0,
            "raw_valid_median_net_worth_at_buy": 850.0,
            "valid_state_share": 0.5,
        },
        {
            "hero_id": 1,
            "item_id": 11,
            "phase": 1,
            "api_avg_net_worth_at_buy": 2_000.0,
            "raw_valid_avg_net_worth_at_buy": 1_900.0,
            "raw_valid_median_net_worth_at_buy": 1_850.0,
            "valid_state_share": 0.9,
        },
    ])


def write_report_inputs(paths: RunPaths, tables: ReportTables) -> None:
    write_json(paths.run / "manifest.json", tables.manifest)
    write_json(
        paths.raw / "heroes.json",
        [{"name": name, "id": hero_id} for name, hero_id in tables.heroes.items()],
    )
    frames = {
        "item_metrics.csv": tables.metrics,
        "estimator_evaluation.csv": tables.evaluation,
        "rank_stability.csv": tables.stability,
        "top10_rankings.csv": tables.rankings,
        "experimental_core_paths.csv": tables.core_paths,
        "core_path_stability.csv": tables.core_path_stability,
        "path_coherence.csv": tables.path_coherence,
        "path_coherence_temporal.csv": tables.path_coherence_temporal,
        "api_event_audit.csv": tables.api_events,
        "account_breadth_stability.csv": tables.account_breadth_stability,
        "api_flow_audit.csv": tables.flow,
        "hero_mechanics_audit.csv": tables.mechanics,
        "hero_ability_scaling.csv": tables.ability_scaling,
        "matchup_interactions.csv": tables.matchups,
        "matchup_temporal_stability.csv": tables.matchup_stability,
        "calibration_sensitivity.csv": tables.calibration,
        "cohort_daily_rank.csv": tables.cohort_daily,
        "cohort_badge_counts.csv": tables.cohort_badges,
        "calibration_item_stability.csv": tables.calibration_item_stability,
        "rank_family_item_stability.csv": tables.rank_item_stability,
        "hero_duration_profiles.csv": tables.durations,
        "match_bootstrap_intervals.csv": tables.bootstrap,
        "purchase_state_coverage.csv": tables.state_coverage,
        "timing_window_stability.csv": tables.timing_stability,
        "sequence_model_evaluation.csv": tables.sequence_evaluation,
        "state_overlap_diagnostics.csv": tables.state_overlap,
        "outcome_confounding_correlations.csv": tables.confounding_correlations,
    }
    for name, frame in frames.items():
        frame.write_csv(paths.tables / name)


def create_report_run(root: Path) -> tuple[RunPaths, ReportTables]:
    paths = RunPaths.create(root, "report-test")
    tables = report_tables()
    write_report_inputs(paths, tables)
    return paths, tables
