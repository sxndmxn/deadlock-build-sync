from __future__ import annotations

import polars as pl

from deadlock_build_sync.value_validation import integer, object_dict, object_rows

from .api import read_json
from .config import RunPaths
from .report_helpers import _weighted_evaluation, _weighted_sequence_evaluation
from .report_types import ReportTables


def load_report_tables(paths: RunPaths) -> ReportTables:
    manifest = object_dict(read_json(paths.run / "manifest.json"))
    if manifest is None:
        raise TypeError("run manifest is not an object")
    hero_rows = object_rows(read_json(paths.raw / "heroes.json"))
    if hero_rows is None:
        raise TypeError("hero assets are not an array of objects")
    heroes = {str(row.get("name")): integer(row["id"]) for row in hero_rows}
    metrics = pl.read_csv(paths.tables / "item_metrics.csv")
    evaluation = _weighted_evaluation(
        pl.read_csv(paths.tables / "estimator_evaluation.csv")
    )
    stability = pl.read_csv(paths.tables / "rank_stability.csv")
    rankings = pl.read_csv(paths.tables / "top10_rankings.csv")
    core_paths = pl.read_csv(paths.tables / "experimental_core_paths.csv")
    core_path_stability = pl.read_csv(paths.tables / "core_path_stability.csv")
    path_coherence = pl.read_csv(paths.tables / "path_coherence.csv")
    path_coherence_temporal = pl.read_csv(paths.tables / "path_coherence_temporal.csv")
    api_events = pl.read_csv(paths.tables / "api_event_audit.csv")
    account_breadth_stability = pl.read_csv(
        paths.tables / "account_breadth_stability.csv"
    )
    flow = pl.read_csv(paths.tables / "api_flow_audit.csv")
    mechanics = pl.read_csv(paths.tables / "hero_mechanics_audit.csv")
    ability_scaling = pl.read_csv(paths.tables / "hero_ability_scaling.csv")
    matchups = pl.read_csv(paths.tables / "matchup_interactions.csv")
    matchup_stability = pl.read_csv(paths.tables / "matchup_temporal_stability.csv")
    calibration = pl.read_csv(paths.tables / "calibration_sensitivity.csv")
    cohort_daily = pl.read_csv(paths.tables / "cohort_daily_rank.csv")
    cohort_badges = pl.read_csv(paths.tables / "cohort_badge_counts.csv")
    calibration_item_stability = pl.read_csv(
        paths.tables / "calibration_item_stability.csv"
    )
    rank_item_stability = pl.read_csv(paths.tables / "rank_family_item_stability.csv")
    durations = pl.read_csv(paths.tables / "hero_duration_profiles.csv")
    bootstrap = pl.read_csv(paths.tables / "match_bootstrap_intervals.csv")
    state_coverage = pl.read_csv(paths.tables / "purchase_state_coverage.csv")
    timing_stability = pl.read_csv(paths.tables / "timing_window_stability.csv")
    sequence_evaluation = _weighted_sequence_evaluation(
        pl.read_csv(paths.tables / "sequence_model_evaluation.csv")
    )
    state_overlap = pl.read_csv(paths.tables / "state_overlap_diagnostics.csv")
    confounding_correlations = pl.read_csv(
        paths.tables / "outcome_confounding_correlations.csv"
    )
    sequence_all_transition = sequence_evaluation.filter(
        (pl.col("evaluation_subset") == "all")
        & (pl.col("model") == "first_order_transition")
    ).row(0, named=True)
    sequence_non_component_transition = sequence_evaluation.filter(
        (pl.col("evaluation_subset") == "non_component")
        & (pl.col("model") == "first_order_transition")
    ).row(0, named=True)
    sequence_all_first_item = sequence_evaluation.filter(
        (pl.col("evaluation_subset") == "all")
        & (pl.col("model") == "first_item_conditioned_transition")
    ).row(0, named=True)
    sequence_non_component_first_item = sequence_evaluation.filter(
        (pl.col("evaluation_subset") == "non_component")
        & (pl.col("model") == "first_item_conditioned_transition")
    ).row(0, named=True)
    sequence_non_component_position = sequence_evaluation.filter(
        (pl.col("evaluation_subset") == "non_component")
        & (pl.col("model") == "hero_position_next_item_popularity")
    ).row(0, named=True)
    return ReportTables(
        manifest=manifest,
        heroes=heroes,
        metrics=metrics,
        evaluation=evaluation,
        stability=stability,
        rankings=rankings,
        core_paths=core_paths,
        core_path_stability=core_path_stability,
        path_coherence=path_coherence,
        path_coherence_temporal=path_coherence_temporal,
        api_events=api_events,
        account_breadth_stability=account_breadth_stability,
        flow=flow,
        mechanics=mechanics,
        ability_scaling=ability_scaling,
        matchups=matchups,
        matchup_stability=matchup_stability,
        calibration=calibration,
        cohort_daily=cohort_daily,
        cohort_badges=cohort_badges,
        calibration_item_stability=calibration_item_stability,
        rank_item_stability=rank_item_stability,
        durations=durations,
        bootstrap=bootstrap,
        state_coverage=state_coverage,
        timing_stability=timing_stability,
        sequence_evaluation=sequence_evaluation,
        state_overlap=state_overlap,
        confounding_correlations=confounding_correlations,
        sequence_all_transition=sequence_all_transition,
        sequence_non_component_transition=sequence_non_component_transition,
        sequence_all_first_item=sequence_all_first_item,
        sequence_non_component_first_item=sequence_non_component_first_item,
        sequence_non_component_position=sequence_non_component_position,
    )
