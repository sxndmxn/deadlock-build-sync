from __future__ import annotations

import polars as pl
from scipy.stats import spearmanr

from .config import PHASES
from .report_helpers import CASE_STUDIES, _case_study
from .report_types import CoreReportContext, PathReportContext, ReportTables


def build_path_report_context(
    tables: ReportTables,
    core: CoreReportContext,
) -> PathReportContext:
    core_paths = tables.core_paths
    path_coherence = tables.path_coherence
    path_coherence_temporal = tables.path_coherence_temporal
    bootstrap = tables.bootstrap
    state_coverage = tables.state_coverage
    flow = tables.flow
    cohort_daily = tables.cohort_daily
    cohort_badges = tables.cohort_badges
    evaluation = tables.evaluation
    rankings = tables.rankings
    heroes = tables.heroes
    stability_summary = core.stability_summary
    event_counts_are_unique = core.event_counts_are_unique
    event_inflation_min = core.event_inflation_min
    event_inflation_max = core.event_inflation_max
    adoption_paths = core_paths.filter(pl.col("method") == "adoption").unique([
        "hero_id",
        "method",
    ])
    adoption_inventory_summary = (
        adoption_paths
        .group_by("final_inventory_items")
        .agg(pl.len().alias("heroes"))
        .sort("final_inventory_items")
    )
    adoption_path_actions = adoption_paths["path_actions"].unique().to_list()
    path_matches = int(path_coherence["player_matches"].sum())

    def weighted_path_share(column: str, weight: str = "player_matches") -> float:
        return float(
            (path_coherence[column] * path_coherence[weight]).sum()
            / path_coherence[weight].sum()
        )

    path_coherence_summary = pl.DataFrame([
        {
            "population": "All eligible matches",
            "matches": path_matches,
            "share_with_six": weighted_path_share("share_with_six"),
            "share_with_eight": weighted_path_share("share_with_eight"),
        },
        {
            "population": "Matches lasting 35m+",
            "matches": int(path_coherence["long_matches"].sum()),
            "share_with_six": weighted_path_share(
                "long_match_share_with_six", "long_matches"
            ),
            "share_with_eight": weighted_path_share(
                "long_match_share_with_eight", "long_matches"
            ),
        },
    ])
    path_lift_summary = path_coherence.select(
        pl.col("six_item_coherence_lift").median().alias("median_six_item_lift"),
        pl.col("eight_item_coherence_lift").median().alias("median_eight_item_lift"),
        pl.col("eight_item_coherence_lift").min().alias("minimum_eight_item_lift"),
    ).row(0, named=True)
    coherence_train = path_coherence_temporal.filter(pl.col("fold") == "train").drop(
        "fold"
    )
    coherence_test = path_coherence_temporal.filter(pl.col("fold") == "test").drop(
        "fold"
    )
    coherence_chronological = coherence_train.join(
        coherence_test, on=["hero_id", "hero_name"], suffix="_test"
    )
    eight_action_coverage_spearman = float(
        spearmanr(
            coherence_chronological["share_with_eight"].to_numpy(),
            coherence_chronological["share_with_eight_test"].to_numpy(),
        ).statistic
    )
    median_eight_action_coverage_shift = float(
        coherence_chronological.select(
            (pl.col("share_with_eight") - pl.col("share_with_eight_test"))
            .abs()
            .median()
        ).item()
    )
    bootstrap_summary = bootstrap.select(
        pl.len().alias("cells"),
        (pl.col("bootstrap_upper") - pl.col("bootstrap_lower"))
        .median()
        .alias("median_interval_width"),
        pl.col("bootstrap_replicates").min().alias("replicates"),
    )
    phase_labels = {phase: label for phase, _, _, label in PHASES}
    state_coverage = state_coverage.with_columns(
        pl.col("phase").replace_strict(phase_labels).alias("phase")
    )
    reconciled_flow = flow.filter(
        pl.col("api_avg_net_worth_at_buy").is_not_null()
        & pl.col("raw_valid_avg_net_worth_at_buy").is_not_null()
    )
    net_worth_rows = [
        {
            "phase": phase_labels[int(row["phase"])],
            **{name: value for name, value in row.items() if name != "phase"},
        }
        for row in reconciled_flow
        .group_by("phase")
        .agg(
            pl.len().alias("cells"),
            pl.col("valid_state_share").median().alias("median_valid_state_share"),
            (
                pl.col("api_avg_net_worth_at_buy")
                / pl.col("raw_valid_avg_net_worth_at_buy")
            )
            .median()
            .alias("median_api_raw_ratio"),
            pl.corr(
                "api_avg_net_worth_at_buy",
                "raw_valid_avg_net_worth_at_buy",
                method="spearman",
            ).alias("spearman"),
        )
        .sort("phase")
        .to_dicts()
    ]
    net_worth_summary = pl.DataFrame(net_worth_rows)
    daily_start = cohort_daily["match_date"].min()
    daily_end = cohort_daily["match_date"].max()
    observed_badge_bounds = cohort_badges.select(
        pl.col("average_badge").min().alias("minimum"),
        pl.col("average_badge").max().alias("maximum"),
    ).row(0, named=True)
    if not isinstance(observed_badge_bounds["minimum"], int) or not isinstance(
        observed_badge_bounds["maximum"], int
    ):
        raise TypeError("observed badge bounds are not integers")
    observed_min_badge = observed_badge_bounds["minimum"]
    observed_max_badge = observed_badge_bounds["maximum"]
    state_estimator = evaluation.filter(pl.col("model") == "state_only_model").row(
        0, named=True
    )
    item_state_estimator = evaluation.filter(
        pl.col("model") == "ridge_state_model"
    ).row(0, named=True)
    adoption_stability = stability_summary.filter(
        pl.col("method") == "adoption_rate"
    ).row(0, named=True)
    ridge_stability = stability_summary.filter(
        pl.col("method") == "ridge_adjusted_rate"
    ).row(0, named=True)
    bootstrap_row = bootstrap_summary.row(0, named=True)
    if event_counts_are_unique:
        event_count_note = (
            "Every retained hero-item cell has exactly one purchase event per "
            "player-match adopter. Event-count ordering and adopter-count ordering "
            "therefore coincide in this snapshot."
        )
    else:
        event_count_note = (
            f"Purchase events per adopter range from {event_inflation_min:.2f} to "
            f"{event_inflation_max:.2f}; affected cells require deduplication."
        )
    kelvin_extra = flow.filter(
        (pl.col("hero_id") == 12)
        & (pl.col("item_id") == 3776945997)
        & (pl.col("phase") == 0)
    )
    kelvin_note = "No reconciled Kelvin Extra Charge row was available."
    if not kelvin_extra.is_empty():
        row = kelvin_extra.row(0, named=True)
        kelvin_note = (
            f"The API reports an average of **{row['api_avg_net_worth_at_buy']:,.0f}** "
            f"souls for the early-phase cell; the raw prior-snapshot-only median is "
            f"**{row['raw_valid_median_net_worth_at_buy']:,.0f}**, and only "
            f"**{row['valid_state_share']:.1%}** of first purchases have valid state."
        )
    cases = "\n".join(
        _case_study(name, heroes[name], rankings, core_paths)
        for name in CASE_STUDIES
        if name in heroes
    )
    phase_text = ", ".join(label for _, _, _, label in PHASES)
    return PathReportContext(
        adoption_paths=adoption_paths,
        adoption_inventory_summary=adoption_inventory_summary,
        adoption_path_actions=adoption_path_actions,
        path_coherence_summary=path_coherence_summary,
        path_lift_summary=path_lift_summary,
        eight_action_coverage_spearman=eight_action_coverage_spearman,
        median_eight_action_coverage_shift=median_eight_action_coverage_shift,
        state_coverage=state_coverage,
        net_worth_summary=net_worth_summary,
        daily_start=daily_start,
        daily_end=daily_end,
        observed_min_badge=observed_min_badge,
        observed_max_badge=observed_max_badge,
        state_estimator=state_estimator,
        item_state_estimator=item_state_estimator,
        adoption_stability=adoption_stability,
        ridge_stability=ridge_stability,
        bootstrap_row=bootstrap_row,
        event_count_note=event_count_note,
        kelvin_note=kelvin_note,
        cases=cases,
        phase_text=phase_text,
    )
