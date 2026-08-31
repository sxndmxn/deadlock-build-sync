from __future__ import annotations

import polars as pl

from .analysis_audit import (
    _account_breadth_stability,
    _api_audit,
    _duration_profiles,
    _effective_property_value,
    _match_bootstrap_intervals,
    _mechanics_audit,
)
from .analysis_base import (
    _add_intervals_and_eb,
    _connection,
    _item_aggregates,
    _outcome_confounding_correlations,
    _state_adjusted,
    _state_overlap_diagnostics,
    _with_matchup_residual,
    _write_csv,
)
from .analysis_cohort import (
    _cohort_adoption_stability,
    _cohort_audits,
    _purchase_state_coverage,
    _sequence_model_evaluation,
)
from .analysis_matchups import (
    _add_same_opportunity_comparators,
    _matchup_temporal_stability,
    _matchups_and_transitions,
)
from .analysis_ridge import (
    _baseline_evaluation,
    _interval_overlap_ratio,
    _rank_stability,
    _ridge_scores,
    _timing_window_stability,
)
from .api import write_json
from .config import RunPaths

__all__ = [
    "_add_same_opportunity_comparators",
    "_effective_property_value",
    "_interval_overlap_ratio",
    "_matchup_temporal_stability",
    "_matchups_and_transitions",
    "_with_matchup_residual",
    "analyze",
]


def analyze(paths: RunPaths) -> dict[str, object]:
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
