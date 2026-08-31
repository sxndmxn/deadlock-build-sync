from __future__ import annotations

import polars as pl

from deadlock_build_sync.value_validation import integer, object_dict

from .report_helpers import _event_inflation_bounds, _format_scope_median
from .report_types import CoreReportContext, ReportTables


def build_core_report_context(tables: ReportTables) -> CoreReportContext:
    manifest = tables.manifest
    metrics = tables.metrics
    rankings = tables.rankings
    state_overlap = tables.state_overlap
    timing_stability = tables.timing_stability
    confounding_correlations = tables.confounding_correlations
    api_events = tables.api_events
    account_breadth_stability = tables.account_breadth_stability
    stability = tables.stability
    core_path_stability = tables.core_path_stability
    calibration = tables.calibration
    cohort_badges = tables.cohort_badges
    calibration_item_stability = tables.calibration_item_stability
    rank_item_stability = tables.rank_item_stability
    durations = tables.durations
    matchups = tables.matchups
    matchup_stability = tables.matchup_stability
    ability_scaling = tables.ability_scaling
    counts = object_dict(manifest.get("extraction")) or {}
    cohort = object_dict(manifest.get("cohort"))
    if cohort is None:
        raise TypeError("run manifest has no cohort object")
    match_count = integer(counts.get("match_folds"), default=0)
    player_match_count = integer(counts.get("player_matches"), default=0)
    hero_count = integer(counts.get("heroes"), default=0)
    purchase_count = integer(counts.get("purchases"), default=0)
    valid_share = integer(counts.get("valid_purchase_net_worth"), default=0) / max(
        1, integer(counts.get("first_purchases"), default=0)
    )
    event_inflation_min, event_inflation_max, event_counts_are_unique = (
        _event_inflation_bounds(metrics)
    )
    most_popular = (
        metrics
        .sort(
            ["hero_id", "tier", "adoption_rate"],
            descending=[False, False, True],
        )
        .group_by(["hero_id", "tier"], maintain_order=True)
        .head(1)
    )
    top_adoption_summary = (
        most_popular
        .group_by("tier")
        .agg(
            pl.len().alias("heroes"),
            pl.col("adoption_rate").min().alias("minimum"),
            pl.col("adoption_rate").median().alias("median"),
            pl.col("adoption_rate").max().alias("maximum"),
        )
        .sort("tier")
    )
    top_adoption_keys = rankings.filter(pl.col("method") == "adoption").select(
        "hero_id", "tier", "item_id"
    )
    top_overlap = top_adoption_keys.join(
        state_overlap, on=["hero_id", "tier", "item_id"], how="inner"
    )
    overlap_summary = (
        top_overlap
        .group_by("tier")
        .agg(
            pl.len().alias("cells"),
            pl.col("state_coverage").median().alias("median_state_coverage"),
            pl.col("effective_support").median().alias("median_effective_support"),
            pl.col("effective_support").min().alias("minimum_effective_support"),
            pl
            .col("effective_support_share")
            .median()
            .alias("median_effective_support_share"),
            pl
            .col("effective_support_share")
            .quantile(0.1)
            .alias("p10_effective_support_share"),
        )
        .sort("tier")
    )
    overall_overlap = top_overlap.select(
        pl.col("effective_support").median().alias("median_effective_support"),
        pl.col("effective_support").min().alias("minimum_effective_support"),
        pl
        .col("effective_support_share")
        .median()
        .alias("median_effective_support_share"),
        pl
        .col("effective_support_share")
        .quantile(0.1)
        .alias("p10_effective_support_share"),
    ).row(0, named=True)
    timing_stability_summary = (
        timing_stability
        .group_by("tier")
        .agg(
            pl.len().alias("cells"),
            pl
            .col("absolute_median_time_shift_s")
            .median()
            .alias("median_time_shift_s"),
            pl.col("time_iqr_overlap").median().alias("median_time_iqr_overlap"),
            pl
            .col("absolute_median_net_worth_shift")
            .median()
            .alias("median_net_worth_shift"),
            pl
            .col("net_worth_iqr_overlap")
            .median()
            .alias("median_net_worth_iqr_overlap"),
        )
        .sort("tier")
    )
    overall_timing_stability = timing_stability.select(
        pl.col("absolute_median_time_shift_s").median().alias("median_time_shift_s"),
        pl.col("time_iqr_overlap").median().alias("median_time_iqr_overlap"),
        pl
        .col("absolute_median_net_worth_shift")
        .median()
        .alias("median_net_worth_shift"),
        pl.col("net_worth_iqr_overlap").median().alias("median_net_worth_iqr_overlap"),
        (pl.col("time_iqr_overlap") < 0.5).mean().alias("low_time_overlap_share"),
        (pl.col("net_worth_iqr_overlap") < 0.5)
        .mean()
        .alias("low_net_worth_overlap_share"),
    ).row(0, named=True)
    confounding_summary = (
        confounding_correlations
        .group_by(["scope", "feature"])
        .agg(
            pl.len().alias("cells"),
            pl.col("spearman").median().alias("median_spearman"),
            pl.col("spearman").quantile(0.1).alias("p10_spearman"),
            pl.col("spearman").quantile(0.9).alias("p90_spearman"),
        )
        .sort(["scope", "median_spearman"], descending=[False, True])
    )
    reconciled_api_events = api_events.filter(
        (pl.col("raw_purchase_events") > 0) & (pl.col("api_purchase_events") > 0)
    )
    api_event_summary = reconciled_api_events.select(
        pl.len().alias("cells"),
        pl.corr("raw_purchase_events", "api_purchase_events", method="spearman").alias(
            "spearman"
        ),
        (pl.col("api_purchase_events") / pl.col("raw_purchase_events"))
        .median()
        .alias("median_api_raw_ratio"),
        (
            (pl.col("api_purchase_events") - pl.col("raw_purchase_events")).abs()
            / pl.col("raw_purchase_events")
        )
        .median()
        .alias("median_absolute_relative_difference"),
        (pl.col("api_unique_accounts") / pl.col("api_purchase_events"))
        .median()
        .alias("median_unique_account_share"),
    )
    api_event_row = api_event_summary.row(0, named=True)
    account_breadth_summary = account_breadth_stability.select(
        pl.len().alias("hero_tier_cells"),
        pl.col("spearman").median().alias("median_spearman"),
        pl.col("top10_jaccard").median().alias("median_top10_jaccard"),
        pl.col("top10_jaccard").min().alias("minimum_top10_jaccard"),
    )
    stability_summary = (
        stability
        .group_by("method")
        .agg(
            pl.col("spearman").median().alias("median_spearman"),
            pl.col("top10_jaccard").median().alias("median_top10_jaccard"),
        )
        .sort("median_spearman", descending=True)
    )
    core_path_stability_summary = core_path_stability.select(
        pl.len().alias("heroes"),
        pl.col("train_legal").sum().alias("train_legal"),
        pl.col("test_legal").sum().alias("test_legal"),
        pl.col("item_set_jaccard").median().alias("median_item_set_jaccard"),
        pl.col("item_set_jaccard").min().alias("minimum_item_set_jaccard"),
        pl.col("ordered_lcs_share").median().alias("median_ordered_lcs_share"),
        pl.col("same_position_share").median().alias("median_same_position_share"),
    )
    core_path_row = core_path_stability_summary.row(0, named=True)
    calibration_summary = (
        calibration
        .group_by("calibration")
        .agg(
            pl.col("player_matches").sum(),
            pl.col("wins").sum(),
        )
        .with_columns((pl.col("wins") / pl.col("player_matches")).alias("outcome_rate"))
        .sort("calibration")
    )
    rank_names = {
        7: "Emissary",
        8: "Oracle",
        9: "Phantom",
        10: "Ascendant",
        11: "Eternus",
    }
    rank_coverage_rows: list[dict[str, object]] = []
    for rank_family, rank_name in rank_names.items():
        family = cohort_badges.filter((pl.col("average_badge") // 10) == rank_family)
        rank_coverage_rows.append({
            "rank_family": rank_name,
            "badge_range": (
                f"{family['average_badge'].min()}–{family['average_badge'].max()}"
                if not family.is_empty()
                else "—"
            ),
            "player_matches": int(family["player_matches"].sum())
            if not family.is_empty()
            else 0,
            "sample_share": (
                float(family["player_matches"].sum()) / max(1, player_match_count)
                if not family.is_empty()
                else 0.0
            ),
        })
    rank_coverage = pl.DataFrame(rank_coverage_rows)
    calibration_adoption_summary = calibration_item_stability.select(
        pl.len().alias("hero_tier_cells"),
        pl.col("spearman").median().alias("median_spearman"),
        pl.col("top10_jaccard").median().alias("median_top10_jaccard"),
    )
    rank_adoption_rows = [
        {
            "comparison": (
                f"{rank_names[int(row['stratum_a'])]} vs "
                f"{rank_names[int(row['stratum_b'])]}"
            ),
            **{
                name: value
                for name, value in row.items()
                if name not in {"stratum_a", "stratum_b"}
            },
        }
        for row in rank_item_stability
        .group_by(["stratum_a", "stratum_b"])
        .agg(
            pl.len().alias("hero_tier_cells"),
            pl.col("shared_items").median().alias("median_shared_items"),
            pl.col("spearman").median().alias("median_spearman"),
            pl.col("top10_jaccard").median().alias("median_top10_jaccard"),
        )
        .sort(["stratum_a", "stratum_b"])
        .to_dicts()
    ]
    rank_adoption_summary = pl.DataFrame(rank_adoption_rows)
    duration_order = {
        "<25m": 0,
        "25-30m": 1,
        "30-35m": 2,
        "35-40m": 3,
        "40-45m": 4,
        "45-50m": 5,
        "50m+": 6,
    }
    duration_summary = (
        durations
        .group_by("duration_bucket")
        .agg(
            pl.col("wins").sum(),
            pl.col("matches").sum(),
            pl.col("ending_outcome_rate").min().alias("minimum_hero_rate"),
            pl.col("ending_outcome_rate").median().alias("median_hero_rate"),
            pl.col("ending_outcome_rate").max().alias("maximum_hero_rate"),
        )
        .with_columns(
            (pl.col("wins") / pl.col("matches")).alias("ending_outcome_rate"),
            pl
            .col("duration_bucket")
            .replace_strict(duration_order)
            .alias("duration_order"),
        )
        .sort("duration_order")
    )
    matchup_summary = (
        matchups
        .group_by("scope")
        .agg(
            pl.len().alias("supported_cells"),
            pl.col("observations").sum(),
            pl
            .col("shrunk_item_residual_delta")
            .abs()
            .median()
            .alias("median_abs_delta"),
        )
        .sort("scope")
    )
    matchup_stability_summary = (
        matchup_stability
        .group_by("scope")
        .agg(
            pl.len().alias("heroes"),
            pl.col("shared_interactions").median(),
            pl.col("spearman").median().alias("median_spearman"),
            pl.col("sign_agreement").median().alias("median_sign_agreement"),
            pl.col("median_absolute_change").median().alias("median_absolute_change"),
        )
        .sort("scope")
    )
    matchup_whole_team_spearman = _format_scope_median(
        matchup_stability_summary, "whole_enemy_team"
    )
    matchup_same_lane_spearman = _format_scope_median(
        matchup_stability_summary, "same_lane"
    )
    mechanic_channels = [
        ("Any active scaled property", pl.col("scaled_property_count") > 0),
        ("Spirit-damage coefficient", pl.col("has_spirit_damage_scaling")),
        ("Duration", pl.col("has_duration_scaling")),
        ("Range or radius", pl.col("has_range_or_radius_scaling")),
        ("Cooldown or recharge", pl.col("has_cooldown_or_recharge_scaling")),
    ]
    mechanic_channel_rows: list[dict[str, object]] = []
    for label, condition in mechanic_channels:
        represented = ability_scaling.filter(condition)
        mechanic_channel_rows.append({
            "channel": label,
            "abilities": represented.height,
            "heroes": represented["hero_id"].n_unique(),
        })
    mechanic_channel_summary = pl.DataFrame(mechanic_channel_rows)
    return CoreReportContext(
        cohort=cohort,
        match_count=match_count,
        player_match_count=player_match_count,
        hero_count=hero_count,
        purchase_count=purchase_count,
        valid_share=valid_share,
        event_inflation_min=event_inflation_min,
        event_inflation_max=event_inflation_max,
        event_counts_are_unique=event_counts_are_unique,
        top_adoption_summary=top_adoption_summary,
        overlap_summary=overlap_summary,
        overall_overlap=overall_overlap,
        timing_stability_summary=timing_stability_summary,
        overall_timing_stability=overall_timing_stability,
        confounding_summary=confounding_summary,
        api_event_row=api_event_row,
        account_breadth_summary=account_breadth_summary,
        stability_summary=stability_summary,
        core_path_stability_summary=core_path_stability_summary,
        core_path_row=core_path_row,
        calibration_summary=calibration_summary,
        rank_coverage=rank_coverage,
        calibration_adoption_summary=calibration_adoption_summary,
        rank_adoption_summary=rank_adoption_summary,
        duration_summary=duration_summary,
        matchup_summary=matchup_summary,
        matchup_stability_summary=matchup_stability_summary,
        matchup_whole_team_spearman=matchup_whole_team_spearman,
        matchup_same_lane_spearman=matchup_same_lane_spearman,
        mechanic_channel_summary=mechanic_channel_summary,
    )
