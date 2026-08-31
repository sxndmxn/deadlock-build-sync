from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import polars as pl

type NumericRow = dict[str, int | float]


@dataclass(frozen=True)
class ReportTables:
    manifest: dict[str, object]
    heroes: dict[str, int]
    metrics: pl.DataFrame
    evaluation: pl.DataFrame
    stability: pl.DataFrame
    rankings: pl.DataFrame
    core_paths: pl.DataFrame
    core_path_stability: pl.DataFrame
    path_coherence: pl.DataFrame
    path_coherence_temporal: pl.DataFrame
    api_events: pl.DataFrame
    account_breadth_stability: pl.DataFrame
    flow: pl.DataFrame
    mechanics: pl.DataFrame
    ability_scaling: pl.DataFrame
    matchups: pl.DataFrame
    matchup_stability: pl.DataFrame
    calibration: pl.DataFrame
    cohort_daily: pl.DataFrame
    cohort_badges: pl.DataFrame
    calibration_item_stability: pl.DataFrame
    rank_item_stability: pl.DataFrame
    durations: pl.DataFrame
    bootstrap: pl.DataFrame
    state_coverage: pl.DataFrame
    timing_stability: pl.DataFrame
    sequence_evaluation: pl.DataFrame
    state_overlap: pl.DataFrame
    confounding_correlations: pl.DataFrame
    sequence_all_transition: NumericRow
    sequence_non_component_transition: NumericRow
    sequence_all_first_item: NumericRow
    sequence_non_component_first_item: NumericRow
    sequence_non_component_position: NumericRow


@dataclass(frozen=True)
class CoreReportContext:
    cohort: dict[str, object]
    match_count: int
    player_match_count: int
    hero_count: int
    purchase_count: int
    valid_share: float
    event_inflation_min: float
    event_inflation_max: float
    event_counts_are_unique: bool
    top_adoption_summary: pl.DataFrame
    overlap_summary: pl.DataFrame
    overall_overlap: NumericRow
    timing_stability_summary: pl.DataFrame
    overall_timing_stability: NumericRow
    confounding_summary: pl.DataFrame
    api_event_row: NumericRow
    account_breadth_summary: pl.DataFrame
    stability_summary: pl.DataFrame
    core_path_stability_summary: pl.DataFrame
    core_path_row: NumericRow
    calibration_summary: pl.DataFrame
    rank_coverage: pl.DataFrame
    calibration_adoption_summary: pl.DataFrame
    rank_adoption_summary: pl.DataFrame
    duration_summary: pl.DataFrame
    matchup_summary: pl.DataFrame
    matchup_stability_summary: pl.DataFrame
    matchup_whole_team_spearman: str
    matchup_same_lane_spearman: str
    mechanic_channel_summary: pl.DataFrame


@dataclass(frozen=True)
class PathReportContext:
    adoption_paths: pl.DataFrame
    adoption_inventory_summary: pl.DataFrame
    adoption_path_actions: list[int]
    path_coherence_summary: pl.DataFrame
    path_lift_summary: NumericRow
    eight_action_coverage_spearman: float
    median_eight_action_coverage_shift: float
    state_coverage: pl.DataFrame
    net_worth_summary: pl.DataFrame
    daily_start: object
    daily_end: object
    observed_min_badge: int
    observed_max_badge: int
    state_estimator: NumericRow
    item_state_estimator: NumericRow
    adoption_stability: NumericRow
    ridge_stability: NumericRow
    bootstrap_row: NumericRow
    event_count_note: str
    kelvin_note: str
    cases: str
    phase_text: str
