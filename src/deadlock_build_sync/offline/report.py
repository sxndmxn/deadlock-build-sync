from __future__ import annotations

from typing import Any

import matplotlib as mpl
import numpy as np
import polars as pl
from scipy.stats import spearmanr

from .api import read_json
from .config import PHASES, RunPaths

mpl.use("Agg")
import matplotlib.pyplot as plt

CASE_STUDIES = ("Abrams", "Haze", "Kelvin", "Dynamo", "Infernus")


def _format_scope_median(frame: pl.DataFrame, scope: str) -> str:
    """Format one optional matchup-stability statistic for prose."""
    scoped = frame.filter(pl.col("scope") == scope)
    if scoped.is_empty():
        return "unavailable"
    value = scoped["median_spearman"].item()
    if value is None or not np.isfinite(value):
        return "unavailable"
    return f"{float(value):.4f}"


def _weighted_evaluation(frame: pl.DataFrame) -> pl.DataFrame:
    return (
        frame
        .with_columns(
            (pl.col("brier") * pl.col("observations")).alias("weighted_brier"),
            (pl.col("log_loss") * pl.col("observations")).alias("weighted_log_loss"),
        )
        .group_by("model")
        .agg(
            pl.col("observations").sum(),
            (pl.col("weighted_brier").sum() / pl.col("observations").sum()).alias(
                "brier"
            ),
            (pl.col("weighted_log_loss").sum() / pl.col("observations").sum()).alias(
                "log_loss"
            ),
        )
        .sort("brier")
    )


def _weighted_sequence_evaluation(frame: pl.DataFrame) -> pl.DataFrame:
    metrics = (
        "context_coverage",
        "target_coverage",
        "top1_accuracy",
        "top3_accuracy",
        "top5_accuracy",
        "mean_reciprocal_rank",
    )
    weighted = frame.with_columns(*[
        (pl.col(metric) * pl.col("test_transitions")).alias(f"weighted_{metric}")
        for metric in metrics
    ])
    return (
        weighted
        .group_by(["evaluation_subset", "model"])
        .agg(
            pl.col("test_transitions").sum(),
            *[
                (
                    pl.col(f"weighted_{metric}").sum()
                    / pl.col("test_transitions").sum()
                ).alias(metric)
                for metric in metrics
            ],
        )
        .sort(
            ["evaluation_subset", "top1_accuracy"],
            descending=[False, True],
        )
    )


def _charts(paths: RunPaths) -> None:
    evaluation = pl.read_csv(paths.tables / "estimator_evaluation.csv")
    summary = _weighted_evaluation(evaluation)
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5))
    labels = summary["model"].to_list()
    axes[0].bar(labels, summary["brier"].to_list(), color="#4472c4")
    axes[1].bar(labels, summary["log_loss"].to_list(), color="#ed7d31")
    axes[0].set_title("Held-out Brier score (lower is better)")
    axes[1].set_title("Held-out log loss (lower is better)")
    for axis in axes:
        axis.tick_params(axis="x", rotation=25)
        axis.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(paths.figures / "heldout-estimator-error.png", dpi=180)
    plt.close(fig)

    stability = pl.read_csv(paths.tables / "rank_stability.csv")
    methods = stability["method"].unique(maintain_order=True).to_list()
    values = [
        stability.filter(pl.col("method") == method)["spearman"].drop_nulls().to_numpy()
        for method in methods
    ]
    fig, axis = plt.subplots(figsize=(9, 4.8))
    axis.boxplot(values, tick_labels=methods, showfliers=False)
    axis.set_ylim(-1.0, 1.0)
    axis.set_ylabel("Train-to-test Spearman correlation")
    axis.set_title("Temporal item-ranking stability by hero and tier")
    axis.grid(axis="y", alpha=0.25)
    axis.tick_params(axis="x", rotation=20)
    fig.tight_layout()
    fig.savefig(paths.figures / "ranking-stability.png", dpi=180)
    plt.close(fig)

    metrics = pl.read_csv(paths.tables / "item_metrics.csv")
    most_popular = (
        metrics
        .sort(
            ["hero_id", "tier", "adoption_rate"],
            descending=[False, False, True],
        )
        .group_by(["hero_id", "tier"], maintain_order=True)
        .head(1)
    )
    fig, axis = plt.subplots(figsize=(8, 4.8))
    for tier in sorted(most_popular["tier"].unique().to_list()):
        values = most_popular.filter(pl.col("tier") == tier)["adoption_rate"].to_numpy()
        axis.scatter(
            np.full(len(values), tier),
            values,
            alpha=0.65,
            s=28,
            label=f"Tier {tier}",
        )
    axis.set_xticks([1, 2, 3, 4])
    axis.set_xlabel("Item tier")
    axis.set_ylabel("Unique player-match adoption rate")
    axis.set_title("True adoption of each hero's most-purchased item")
    axis.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(paths.figures / "top-item-adoption.png", dpi=180)
    plt.close(fig)

    flow = pl.read_csv(paths.tables / "api_flow_audit.csv")
    early = flow.filter(
        (pl.col("phase") == 0)
        & pl.col("api_avg_net_worth_at_buy").is_not_null()
        & pl.col("raw_valid_median_net_worth_at_buy").is_not_null()
    )
    if not early.is_empty():
        fig, axis = plt.subplots(figsize=(6.5, 6))
        x = early["raw_valid_median_net_worth_at_buy"].to_numpy()
        y = early["api_avg_net_worth_at_buy"].to_numpy()
        axis.scatter(x, y, alpha=0.25, s=10)
        maximum = float(max(np.max(x), np.max(y)))
        axis.plot([0, maximum], [0, maximum], linestyle="--", color="black")
        axis.set_xlabel("Raw median using prior snapshots only")
        axis.set_ylabel("API average net worth at buy")
        axis.set_title("Early-purchase net-worth audit")
        axis.grid(alpha=0.2)
        fig.tight_layout()
        fig.savefig(paths.figures / "early-net-worth-audit.png", dpi=180)
        plt.close(fig)

    overlap = pl.read_csv(paths.tables / "state_overlap_diagnostics.csv")
    rankings = pl.read_csv(paths.tables / "top10_rankings.csv").filter(
        pl.col("method") == "adoption"
    )
    top_overlap = rankings.select("hero_id", "tier", "item_id").join(
        overlap, on=["hero_id", "tier", "item_id"], how="inner"
    )
    raw_observations = top_overlap["item_observations"].to_numpy()
    effective_support = top_overlap["effective_support"].to_numpy()
    fig, axis = plt.subplots(figsize=(7.2, 6))
    for tier in sorted(top_overlap["tier"].unique().to_list()):
        tier_rows = top_overlap.filter(pl.col("tier") == tier)
        axis.scatter(
            tier_rows["item_observations"].to_numpy(),
            tier_rows["effective_support"].to_numpy(),
            alpha=0.45,
            s=18,
            label=f"Tier {tier}",
        )
    lower = float(min(np.min(raw_observations), np.min(effective_support)))
    upper = float(max(np.max(raw_observations), np.max(effective_support)))
    axis.plot([lower, upper], [lower, upper], color="black", linestyle="--")
    axis.set_xscale("log")
    axis.set_yscale("log")
    axis.set_xlabel("Raw item observations")
    axis.set_ylabel("Overlap-weighted effective support")
    axis.set_title("Comparable-state support can collapse despite high volume")
    axis.grid(alpha=0.2)
    axis.legend()
    fig.tight_layout()
    fig.savefig(paths.figures / "state-effective-support.png", dpi=180)
    plt.close(fig)


def _markdown_table(frame: pl.DataFrame, columns: list[tuple[str, str]]) -> str:
    def cell(value: object) -> str:
        return str(value).replace("|", "\\|").replace("\n", "<br>")

    header = "| " + " | ".join(cell(label) for _, label in columns) + " |"
    separator = "| " + " | ".join("---" for _ in columns) + " |"
    rows = [header, separator]
    for row in frame.to_dicts():
        values: list[str] = []
        for name, _ in columns:
            value = row.get(name)
            if isinstance(value, float):
                values.append(f"{value:.4f}")
            else:
                values.append(cell(value))
        rows.append("| " + " | ".join(values) + " |")
    return "\n".join(rows)


def _case_study(
    hero_name: str, hero_id: int, rankings: pl.DataFrame, paths: pl.DataFrame
) -> str:
    selected = rankings.filter(
        (pl.col("hero_id") == hero_id)
        & pl.col("method").is_in([
            "adoption",
            "empirical_bayes_mean",
            "state_adjusted_eb",
            "ridge_adjusted",
        ])
        & (pl.col("rank") <= 3)
    ).select("tier", "method", "rank", "item_name", "adoption_rate", "raw_outcome_rate")
    path_summary = (
        paths
        .filter(pl.col("hero_id") == hero_id)
        .sort(["method", "step"])
        .group_by("method")
        .agg(
            pl.col("path_legal").first(),
            pl.col("path_actions").first(),
            pl.col("path_cost").first(),
            pl.col("item_name").str.join(" → ").alias("purchase_order"),
        )
        .sort("method")
    )
    return f"""
### {hero_name}

Top three items per tier under four materially different estimators:

{_markdown_table(selected, [("tier", "Tier"), ("method", "Method"), ("rank", "Rank"), ("item_name", "Item"), ("adoption_rate", "Adoption"), ("raw_outcome_rate", "Raw outcome")])}

<details>
<summary>Illustrative legal core paths</summary>

{_markdown_table(path_summary, [("method", "Method"), ("path_legal", "Legal"), ("path_actions", "Actions"), ("path_cost", "Cost"), ("purchase_order", "Observed-time order")])}

</details>
"""


def _event_inflation_bounds(metrics: pl.DataFrame) -> tuple[float, float, bool]:
    bounds = metrics.select(
        pl.col("event_inflation").min().alias("minimum"),
        pl.col("event_inflation").max().alias("maximum"),
    ).row(0, named=True)
    if not isinstance(bounds["minimum"], (int, float)) or not isinstance(
        bounds["maximum"], (int, float)
    ):
        raise TypeError("event-inflation bounds are not numeric")
    minimum = float(bounds["minimum"])
    maximum = float(bounds["maximum"])
    counts_are_unique = abs(minimum - 1.0) < 1e-12 and abs(maximum - 1.0) < 1e-12
    return minimum, maximum, counts_are_unique


def render_report(paths: RunPaths) -> dict[str, Any]:
    _charts(paths)
    manifest = read_json(paths.run / "manifest.json")
    heroes = {
        str(row.get("name")): int(row["id"])
        for row in read_json(paths.raw / "heroes.json")
    }
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

    counts = manifest.get("extraction", {})
    valid_share = counts.get("valid_purchase_net_worth", 0) / max(
        1, counts.get("first_purchases", 0)
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
    rank_coverage_rows: list[dict[str, Any]] = []
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
                float(family["player_matches"].sum()) / counts.get("player_matches", 1)
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
    rank_adoption_rows: list[dict[str, Any]] = []
    for row in (
        rank_item_stability
        .group_by(["stratum_a", "stratum_b"])
        .agg(
            pl.len().alias("hero_tier_cells"),
            pl.col("shared_items").median().alias("median_shared_items"),
            pl.col("spearman").median().alias("median_spearman"),
            pl.col("top10_jaccard").median().alias("median_top10_jaccard"),
        )
        .sort(["stratum_a", "stratum_b"])
        .to_dicts()
    ):
        rank_adoption_rows.append({
            "comparison": (
                f"{rank_names[int(row['stratum_a'])]} vs "
                f"{rank_names[int(row['stratum_b'])]}"
            ),
            **{
                name: value
                for name, value in row.items()
                if name not in {"stratum_a", "stratum_b"}
            },
        })
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
    mechanic_channel_rows: list[dict[str, Any]] = []
    for label, condition in mechanic_channels:
        represented = ability_scaling.filter(condition)
        mechanic_channel_rows.append({
            "channel": label,
            "abilities": represented.height,
            "heroes": represented["hero_id"].n_unique(),
        })
    mechanic_channel_summary = pl.DataFrame(mechanic_channel_rows)
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
    net_worth_rows: list[dict[str, Any]] = []
    for row in (
        reconciled_flow
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
    ):
        net_worth_rows.append({
            "phase": phase_labels[int(row["phase"])],
            **{name: value for name, value in row.items() if name != "phase"},
        })
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
    report = rf"""---
title: Deadlock Item-Ranking Evidence Study
cohort: Configured Emissary I–Eternus V; observed Emissary–Phantom
generated: {manifest.get("generated_at")}
---

# Deadlock Item-Ranking Evidence Study

> [!IMPORTANT]
> The evidence is sufficient to select an algorithm family, but not to treat an item/outcome association as causal. The recommended system deliberately keeps popularity, conditional outcome, uncertainty, tactical interpretation, and path legality as separate layers.

## Executive summary

The frozen post-reset cohort contains **{counts.get("match_folds", 0):,} matches**, **{counts.get("player_matches", 0):,} hero-player observations**, **{counts.get("heroes", 0)} heroes**, and **{counts.get("purchases", 0):,} qualifying purchase events**. The analysis covers ranked normal matches from `{manifest["cohort"]["since"]}` through `{manifest["cohort"]["as_of"]}`, using numeric badges **71–115**.

That badge range is the configured acceptance window, not the observed rank coverage. The frozen post-reset sample actually spans **{observed_min_badge}–{observed_max_badge}**: Emissary through Phantom. It contains no Ascendant or Eternus average-rank matches yet, so the combined findings must not be presented as Eternus-specific evidence.

The main findings are:

1. **Use true adoption for popularity.** {event_count_note} That does not make “percentage of the most popular item” an adoption rate: the most popular item is not purchased by every hero-player observation.
2. **Game state predicts outcome; item identity did not add validated ranking signal.** The state-only control is the best held-out predictor with Brier **{state_estimator["brier"]:.6f}**. Adding item identity yields **{item_state_estimator["brier"]:.6f}**, while its train/test item-order Spearman is only **{ridge_stability["median_spearman"]:.4f}**. Do not use the ridge item score to select the core.
3. **Adoption is much more temporally stable than outcome ordering.** Its median train/test Spearman correlation is **{adoption_stability["median_spearman"]:.4f}**, with median top-ten Jaccard **{adoption_stability["median_top10_jaccard"]:.4f}**.
4. **Wilson is an uncertainty display, not the build algorithm.** It is conservative but does not pool related cells or correct purchase-state selection.
5. **Adjustment is only as good as its pre-decision state.** Only **{valid_share:.1%}** of first-purchase rows have a temporally valid net-worth snapshot. Missing opening state must remain missing or become its own stratum.
6. **Provisional rank status does not destabilize popularity here.** Calibrated-versus-provisional adoption has median Spearman **{calibration_adoption_summary.row(0, named=True)["median_spearman"]:.4f}** and median top-ten Jaccard **{calibration_adoption_summary.row(0, named=True)["median_top10_jaccard"]:.4f}**. This supports pooling calibration states for popularity while retaining the audit.
7. **Raw support is not comparable-state support.** Among top-ten adopted items, median overlap-weighted effective support is only **{overall_overlap["median_effective_support_share"]:.1%}** of raw observations; its 10th percentile is **{overall_overlap["p10_effective_support_share"]:.1%}**. Outcome contrasts need phase/position-specific candidate slates and explicit no-overlap abstention.
8. **Matchup outcome deltas do not survive main-effect adjustment reliably.** After subtracting each hero-versus-enemy baseline, median chronological Spearman is **{matchup_same_lane_spearman}** for same-lane residuals and **{matchup_whole_team_spearman}** for whole-team residuals. Counter purchases must start from mechanics and use these residuals only as an abstention-gated audit.
9. **A single marginal top-item path can mix persistent build archetypes.** Eight-action co-purchase coverage varies by hero but is itself highly chronological-stable (train/test Spearman **{eight_action_coverage_spearman:.4f}**). Core selection therefore needs an archetype-aware sequence model, not just marginal adoption sorted by time.

{kelvin_note}

![Held-out estimator error](figures/heldout-estimator-error.png)

## Cohort and evidence contract

| Property | Value |
| --- | --- |
| Mode | Ranked / Normal |
| Configured rank range | Emissary I `[71]` – Eternus V `[115]` |
| Observed average-badge range | `{observed_min_badge}`–`{observed_max_badge}` (Emissary–Phantom) |
| Start | July 30, 2026 rank reset |
| Phases | {phase_text} |
| Active heroes | {counts.get("heroes", 0)} |
| Purchase unit | First purchase per player-match-item for adoption; all events retained for inflation audits |
| Outcome | Final valid win/loss; observational association |
| Buy-state rule | Latest telemetry snapshot at or before purchase; no future/final fallback |

The complete machine-readable identity is in [`manifest.json`](manifest.json). Public account IDs are never persisted.

## Recommended algorithm architecture

The production design should be a constrained, layered recommender:

1. **Eligibility:** require current-patch support, valid item assets, hero availability, rank cohort, and minimum unique player-match support.
2. **Popularity signal:** calculate `adoption = unique hero-player matches buying the item / eligible hero-player matches`. Keep purchase-event count only as an audit field.
3. **Context baseline:** model phase, buy time, rank, prior net worth, team lead, prior spend, and prior purchase count using only information known at the decision. Use this to identify selection bias and compare like-for-like states—not to award points merely because an item is bought by players already ahead.
4. **Partial pooling and confidence:** shrink sparse hero/tier/item or matchup cells with hierarchical beta-binomial empirical Bayes. Publish posterior intervals or Wilson intervals beside estimates; do not sort the core build by Wilson lower bound alone.
5. **Core selection and archetypes:** shortlist stable, well-supported items by adoption percentile within hero/tier, then require match-level co-purchase coherence. Fit a held-out-selected mixture of purchase-sequence models per hero so the default path comes from one common archetype instead of combining marginally popular but mutually substitutable items. Treat empirical-Bayes outcome and state-adjusted outcome as labeled secondary evidence, not core ranking inputs, until an item-effect model beats the state-only ablation and is temporally stable.
6. **Situational selection:** generate branches from shrunk, main-effect-adjusted same-lane and whole-team item residuals only when item mechanics support the counter rationale and the cell has adequate support, effective sample size, interval width, and temporal stability.
7. **Path optimization:** within an eligible archetype, choose at least eight purchase actions, then optimize observed transition support plus timing and valid net-worth windows while enforcing component credit, inventory slots, active-item limits, total budget, and explicit sells/upgrades. Purchase actions and final inventory count are separate concepts.

Do not collapse these layers into an unexplained fixed weighted average yet. The evidence supports a lexicographic policy today: pass legality/support checks, shortlist by stable adoption within tier, select a co-purchase-coherent archetype, use transition and timing evidence to construct the path, and expose outcome estimates with their uncertainty. A future outcome contribution must earn its place through an incremental state-only ablation, temporal rank stability, and prospective build evaluation.

For hero \(h\) and item \(i\), the core prevalence feature is:

\[
A_{{h,i}} = \frac{{\#\text{{ unique eligible hero-player matches buying }}i}}{{\#\text{{ eligible hero-player matches for }}h}}
\]

After an adoption/support shortlist is fixed, order a candidate path \(\pi=(i_1,\ldots,i_K)\) with a smoothed transition-and-timing objective such as:

\[
J(\pi)=\sum_{{k=2}}^K \log \widetilde P(i_k\mid i_{{k-1}},h)
-\lambda\sum_{{k=1}}^K \rho\!\left(t_k-\widetilde t_{{h,i_k}}\right)
\]

Here \(\widetilde P\) backs sparse transition edges off toward hero/position popularity, \(\widetilde t\) is the observed median purchase time, and \(\rho\) is a robust timing-loss function. Tune the smoothing strength and \(\lambda\) on the validation fold using next-action ranking and path-stability metrics. Components, slots, actives, budget, sells, and flex state remain hard constraints, not score penalties. Observed outcome rate does not enter this objective under the current evidence.

## Estimator comparison

{_markdown_table(evaluation, [("model", "Estimator"), ("observations", "Held-out observations"), ("brier", "Brier ↓"), ("log_loss", "Log loss ↓")])}

Interpretation:

- **Raw outcome rate** is readable but overreacts to sparse cells and purchase-state selection.
- **Wilson lower bound** is conservative but systematically combines effect size with support; it is not a shrinkage model or a causal adjustment.
- **Empirical-Bayes mean** learns a beta prior within each hero and tier, then allows high-support items to remain close to their observed rate.
- **State-adjusted EB** post-stratifies purchase choices over shared phase/net-worth/lead cells and reports coverage.
- **Ridge state model** standardizes item coefficients over a common observed-state sample. It is a sensitivity model, not a causal estimate.

The state-only ablation is decisive for current implementation: the item-augmented ridge model does not improve held-out prediction and its item order is unstable. Use the regularized state model as a confounding diagnostic, empirical Bayes for sparse descriptive cells, and adoption for the core ranking. Wilson remains useful as a visible confidence bound. A cross-fitted doubly robust or hierarchical outcome model is worth testing later, but it should not influence builds unless it adds held-out value beyond state and yields stable item contrasts under adequate overlap.

### Luxury-item confounding

Spearman correlation between item-level raw outcome and common selection variables:

{_markdown_table(confounding_summary, [("scope", "Scope"), ("feature", "Feature"), ("cells", "Cells"), ("median_spearman", "Median Spearman"), ("p10_spearman", "P10"), ("p90_spearman", "P90")])}

Across a hero's full catalog, expensive later purchases mechanically select for matches in which the buyer remained able to shop. Tier stratification removes the cost variation and substantially reduces—but does not eliminate—the time/net-worth association. Item tier must therefore be a comparison stratum, not a feature whose coefficient is interpreted as item power.

### State overlap and effective support

![Raw observations versus overlap-weighted effective support](figures/state-effective-support.png)

{_markdown_table(overlap_summary, [("tier", "Tier"), ("cells", "Top-item cells"), ("median_state_coverage", "Median state coverage"), ("median_effective_support", "Median ESS"), ("minimum_effective_support", "Minimum ESS"), ("median_effective_support_share", "Median ESS/raw"), ("p10_effective_support_share", "P10 ESS/raw")])}

Coverage alone looks reassuring, but the weight concentration does not. Some widely purchased opening items occupy such narrow states that standardizing them over the full hero/tier distribution leaves almost no effective comparison sample. Therefore `state_adjusted_eb` and `ridge_adjusted_rate` are sensitivity columns only. A future causal estimator should define the decision at a specific phase/position, estimate treatment propensity within the available candidate slate, use overlap weights or a cross-fitted doubly robust estimator, report effective support and maximum weight, and abstain when overlap fails.

## Temporal stability

![Ranking stability](figures/ranking-stability.png)

{_markdown_table(stability_summary, [("method", "Method"), ("median_spearman", "Median Spearman"), ("median_top10_jaccard", "Median top-10 Jaccard")])}

These metrics use a strict chronological 60%/20%/20% match split. Stability measures reproducibility across time, not strategic correctness.

The empirical-Bayes lower bound is roughly as stable as Wilson—not better—while the posterior mean is substantially less stable than adoption. Empirical Bayes is still preferable when a coherent partially pooled estimate is needed, but this dataset does not support using either lower bound as the primary ordering.

The stability check was also applied to the complete adoption-derived purchase path:

{_markdown_table(core_path_stability_summary, [("heroes", "Heroes"), ("train_legal", "Train paths legal"), ("test_legal", "Test paths legal"), ("median_item_set_jaccard", "Median item-set Jaccard"), ("minimum_item_set_jaccard", "Minimum item-set Jaccard"), ("median_ordered_lcs_share", "Median ordered overlap"), ("median_same_position_share", "Median same-position share")])}

The median path retains **{core_path_row["median_item_set_jaccard"]:.1%}** item-set agreement and **{core_path_row["median_ordered_lcs_share"]:.1%}** ordered overlap across time, and every split-specific path remains legal. The minimum item-set agreement is **{core_path_row["minimum_item_set_jaccard"]:.1%}**, so per-hero refresh/fingerprinting is still necessary even though the population-level method is stable.

## Sequence coherence

Held-out next-purchase imitation across the chronological test set:

{_markdown_table(sequence_evaluation, [("evaluation_subset", "Subset"), ("model", "Model"), ("test_transitions", "Test transitions"), ("target_coverage", "Target coverage"), ("top1_accuracy", "Top-1"), ("top3_accuracy", "Top-3"), ("top5_accuracy", "Top-5"), ("mean_reciprocal_rank", "MRR")])}

The first-order transition model predicts the exact next item at rank one in **{sequence_all_transition["top1_accuracy"]:.1%}** of **{int(sequence_all_transition["test_transitions"]):,}** held-out transitions and places it in the top five **{sequence_all_transition["top5_accuracy"]:.1%}** of the time. Conditioning that transition on the build's first purchase raises top-one accuracy to **{sequence_all_first_item["top1_accuracy"]:.1%}** and top-five to **{sequence_all_first_item["top5_accuracy"]:.1%}**, with **{sequence_all_first_item["context_coverage"]:.1%}** context coverage. After removing direct component-to-upgrade transitions, first-purchase conditioning raises top-one accuracy from **{sequence_non_component_transition["top1_accuracy"]:.1%}** to **{sequence_non_component_first_item["top1_accuracy"]:.1%}** and top-five from **{sequence_non_component_transition["top5_accuracy"]:.1%}** to **{sequence_non_component_first_item["top5_accuracy"]:.1%}**, versus **{sequence_non_component_position["top1_accuracy"]:.1%}** top-one for the hero-and-purchase-position baseline. These transition metrics remain review evidence only; they do not select runtime actions.

### Deterministic route policy

For each supported legal eight-item core, target ordering is a constrained ranking problem. Every observed pair of target purchases contributes a precedence vote when their timestamps differ. A subset dynamic program chooses the mechanics-legal permutation with maximum pairwise agreement among orders whose component-expanded path admits a nondecreasing soul checkpoint through every observed first-ownership IQR. Item IDs break exact score ties. Equal-time purchases remain an unordered choice set and cast no artificial precedence vote; observed outcome rates remain descriptive and never enter ordering.

Each candidate target order is expanded through the current component graph during constrained optimization. Candidate admission proves the expanded path is unique, legal, soul-window feasible, within the median final-net-worth budget, and resolves to the selected final inventory. A near-variant diagnostic records a materially different runner-up when it retains at least 90% of the winning agreement score. The typed `BuildPolicy` graph is the sole runtime authority; observational transition tables cannot override it or supply a popularity fallback.

## Data-quality findings

### Event count versus adoption

![True adoption of each hero's most-purchased item](figures/top-item-adoption.png)

{event_count_note} The missing denominator is still decisive: dividing by the largest item count makes one item read as 100% for every hero even when only a fraction of eligible matches bought it.

{_markdown_table(top_adoption_summary, [("tier", "Tier"), ("heroes", "Heroes"), ("minimum", "Minimum top adoption"), ("median", "Median top adoption"), ("maximum", "Maximum top adoption")])}

### Aggregate API reconciliation

Across **{api_event_row["cells"]:,}** reconciled hero-item cells, raw and aggregate API event counts have Spearman **{api_event_row["spearman"]:.6f}**. The median absolute relative difference is **{api_event_row["median_absolute_relative_difference"]:.2%}**, consistent with closely aligned but not perfectly simultaneous source snapshots. The API's unique-account count is a median **{api_event_row["median_unique_account_share"]:.2%}** of event volume. Unique accounts are useful for player-concentration audits, but they are not unique hero-player-match adopters and cannot be substituted into the adoption formula.

Match adoption and unique-account breadth nevertheless produce nearly identical orderings:

{_markdown_table(account_breadth_summary, [("hero_tier_cells", "Hero/tier cells"), ("median_spearman", "Median Spearman"), ("median_top10_jaccard", "Median top-10 Jaccard"), ("minimum_top10_jaccard", "Minimum top-10 Jaccard")])}

This supports match adoption as the primary estimand in the current cohort while keeping account breadth as a repeat-player robustness audit.

### Net worth at purchase

![Early net-worth audit](figures/early-net-worth-audit.png)

For early purchases, a large share of players have no telemetry snapshot preceding the buy. Substituting final net worth leaks future information and makes wealthy winners appear wealthy at minute zero. The raw reconstruction quarantines those rows.

Purchase-weighted state coverage:

{_markdown_table(state_coverage, [("phase", "Phase"), ("purchases", "Purchases"), ("own_net_worth_share", "Own net-worth share"), ("team_lead_share", "Team-lead share"), ("complete_team_snapshot_share", "Complete-team snapshot share"), ("complete_share_when_lead_present", "Complete when lead present")])}

{_markdown_table(net_worth_summary, [("phase", "Phase"), ("cells", "Reconciled cells"), ("median_valid_state_share", "Median valid-state share"), ("median_api_raw_ratio", "Median API/raw average ratio"), ("spearman", "API/raw Spearman")])}

The aggregate API and raw prior-snapshot reconstruction agree almost exactly after nine minutes. The opening phase is qualitatively different: its negative cross-item correlation and extreme ratios show that API purchase net worth is not a safe opening-buy feature. Opening recommendations should use observed order/time and item cost, explicitly marking net-worth state unavailable where no prior snapshot exists.

For the 1,520 most-adopted hero/tier/item cells, chronological purchase windows are usually reproducible:

{_markdown_table(timing_stability_summary, [("tier", "Tier"), ("cells", "Top-item cells"), ("median_time_shift_s", "Median buy-time shift (s)"), ("median_time_iqr_overlap", "Median time-IQR overlap"), ("median_net_worth_shift", "Median net-worth shift"), ("median_net_worth_iqr_overlap", "Median net-worth-IQR overlap")])}

Overall, the median train/test buy-time shift is **{overall_timing_stability["median_time_shift_s"]:.1f} seconds** with **{overall_timing_stability["median_time_iqr_overlap"]:.3f}** IQR overlap. The median valid net-worth shift is **{overall_timing_stability["median_net_worth_shift"]:.1f} souls** with **{overall_timing_stability["median_net_worth_iqr_overlap"]:.3f}** overlap. Only **{overall_timing_stability["low_time_overlap_share"]:.1%}** of time windows and **{overall_timing_stability["low_net_worth_overlap_share"]:.1%}** of net-worth windows have overlap below 0.5. Use these as ranges with per-item stability gates, never as exact purchase deadlines; opening net-worth windows still abstain when no prior snapshot exists. See [`timing_window_stability.csv`](tables/timing_window_stability.csv).

### Calibration and cohort composition

The frozen cohort spans **{daily_start} through {daily_end}**. Counts by day and broad rank tier are exported so post-reset population drift can be audited rather than silently mixed into item effects.

{_markdown_table(rank_coverage, [("rank_family", "Rank family"), ("badge_range", "Observed badge range"), ("player_matches", "Player matches"), ("sample_share", "Sample share")])}

{_markdown_table(calibration_summary, [("calibration", "Calibration"), ("player_matches", "Player matches"), ("outcome_rate", "Outcome rate")])}

Calibrated-versus-provisional item adoption remains highly consistent across all **{calibration_adoption_summary.row(0, named=True)["hero_tier_cells"]}** hero/tier cells:

{_markdown_table(calibration_adoption_summary, [("hero_tier_cells", "Hero/tier cells"), ("median_spearman", "Median Spearman"), ("median_top10_jaccard", "Median top-10 Jaccard")])}

Observed rank-family comparisons:

{_markdown_table(rank_adoption_summary, [("comparison", "Comparison"), ("hero_tier_cells", "Hero/tier cells"), ("median_shared_items", "Median shared items"), ("median_spearman", "Median Spearman"), ("median_top10_jaccard", "Median top-10 Jaccard")])}

Emissary and Oracle dominate the sample. Phantom comparisons have fewer shared supported items, and Ascendant/Eternus cannot be evaluated from this frozen window.

See [`cohort_daily_rank.csv`](tables/cohort_daily_rank.csv) for daily composition, [`cohort_badge_counts.csv`](tables/cohort_badge_counts.csv) for exact badge coverage, [`calibration_item_stability.csv`](tables/calibration_item_stability.csv) for provisional-rank sensitivity, and [`rank_family_item_stability.csv`](tables/rank_family_item_stability.csv) for rank-family comparisons.

### Ending-time profiles

{_markdown_table(duration_summary, [("duration_bucket", "Game ending duration"), ("matches", "Hero observations"), ("minimum_hero_rate", "Minimum hero rate"), ("median_hero_rate", "Median hero rate"), ("maximum_hero_rate", "Maximum hero rate")])}

These are hero results among games that *ended* in each interval. They are a duration sensitivity table—not a live, minute-by-minute power curve and not proof of a hero power spike.

### Matchup scope and uncertainty

{_markdown_table(matchup_summary, [("scope", "Enemy scope"), ("supported_cells", "Supported hero-item-enemy cells"), ("observations", "Observations"), ("median_abs_delta", "Median |adjusted item residual|")])}

Whole-enemy-team and assigned-same-lane associations are kept separate. Each item/enemy delta is shrunk toward that item's hero-wide outcome and then subtracts the correspondingly shrunk hero-versus-enemy main effect. This difference-in-differences-style residual prevents a hero's ordinary good or bad matchup from being mislabeled as an item counter, but it remains observational rather than causal. The raw item outcome intervals were also resampled over **{int(bootstrap_row["cells"]):,}** supported top-item cells with **{int(bootstrap_row["replicates"])}** replicates; the median 95% interval width is **{bootstrap_row["median_interval_width"]:.4f}**. A matchup recommendation still requires a compatible item mechanic before it can become counter-purchase prose.

Chronological train/test reproducibility of the main-effect-adjusted item residuals:

{_markdown_table(matchup_stability_summary, [("scope", "Enemy scope"), ("heroes", "Heroes"), ("shared_interactions", "Median shared interactions"), ("median_spearman", "Median Spearman"), ("median_sign_agreement", "Median sign agreement"), ("median_absolute_change", "Median absolute delta change")])}

These matchup residuals are suitable only for evidence-gathering behind a mechanics gate. Their chronological reproducibility determines whether a candidate survives at all; an outcome residual alone must never declare a counter item.

### Mechanics coverage

The frozen client assets resolve **{ability_scaling.height}** signature abilities and expose their active scaled properties without assigning a guessed synergy score:

{_markdown_table(mechanic_channel_summary, [("channel", "Source scaling channel"), ("abilities", "Abilities represented"), ("heroes", "Heroes represented")])}

The sole exception to active scaling-property coverage is Vyper's **Slither**, an innate movement modifier whose current asset payload contains no non-sentinel scaled property. The generator must preserve that absence rather than infer a coefficient.

{_markdown_table(mechanics, [("hero_name", "Hero"), ("signature_abilities", "Signature refs"), ("resolved_abilities", "Resolved"), ("abilities_with_scaling", "Scaling represented")])}

[`hero_ability_scaling.csv`](tables/hero_ability_scaling.csv) preserves ability slot, source class/name, scaled property names, scale functions, specific stat types, and Spirit-damage coefficients. Mechanics are used only to validate item identity, components, cost, inventory capacity, active-item limits, ability references, and an explicit item-to-ability rationale. They are not converted into an unvalidated numeric affinity score.

## All-hero ranking and path artifacts

The current adoption baseline produces **{adoption_paths.height}** legal hero paths with **{", ".join(str(value) for value in sorted(adoption_path_actions))} purchase actions each**. Component upgrades consume their prerequisites, so action count and final inventory count intentionally differ:

{_markdown_table(adoption_inventory_summary, [("final_inventory_items", "Final owned items after upgrades"), ("heroes", "Heroes")])}

This is never a four-item recommendation. The top-ten evidence slate, the 8–12-action purchase path, and the final slot-constrained inventory are separate outputs.

Marginal popularity alone is not sufficient evidence that all ten actions belong to one build. The in-sample co-purchase audit shows:

{_markdown_table(path_coherence_summary, [("population", "Population"), ("matches", "Hero-player matches"), ("share_with_six", "Bought ≥6 path actions"), ("share_with_eight", "Bought ≥8 path actions")])}

Across heroes, median observed-versus-independent co-purchase lift is **{path_lift_summary["median_six_item_lift"]:.3f}** for six actions and **{path_lift_summary["median_eight_item_lift"]:.3f}** for eight. The weakest eight-action lift is only **{path_lift_summary["minimum_eight_item_lift"]:.3f}**, showing that some marginal top-item paths combine alternatives. Long matches barely improve eight-action coverage, so duration attrition is not the whole explanation. These patterns persist chronologically: train/test per-hero eight-action coverage has Spearman **{eight_action_coverage_spearman:.3f}** and median absolute shift **{median_eight_action_coverage_shift:.1%}**. The production algorithm should learn latent purchase archetypes (for example, a small held-out-selected mixture of smoothed first-order sequence models) and require held-out co-purchase lift/coverage before emitting a path. [`path_coherence.csv`](tables/path_coherence.csv) exposes the per-hero audit; current paths remain baselines, not finished build recommendations.

- [`top10_rankings.csv`](tables/top10_rankings.csv) contains exactly ten supported items per hero/tier/method when ten exist.
- [`account_breadth_stability.csv`](tables/account_breadth_stability.csv) compares match adoption with unique-player breadth without persisting account identifiers.
- [`experimental_core_paths.csv`](tables/experimental_core_paths.csv) contains method-specific 8–12-purchase paths capped at 30k souls.
- [`core_path_stability.csv`](tables/core_path_stability.csv) compares adoption-derived train/test paths item-for-item and in order.
- [`path_coherence.csv`](tables/path_coherence.csv) compares full-path co-purchase coverage with an independent-adoption baseline per hero.
- [`path_coherence_temporal.csv`](tables/path_coherence_temporal.csv) checks whether per-hero path coverage reproduces across chronological folds.
- [`matchup_interactions.csv`](tables/matchup_interactions.csv) separates enemy-conditioned item associations from both global item outcomes and hero-matchup main effects.
- [`matchup_temporal_stability.csv`](tables/matchup_temporal_stability.csv) measures whether those adjusted item residuals reproduce chronologically.
- [`item_transitions.csv`](tables/item_transitions.csv) records observed next-item sequences without treating them as causal synergy.
- [`sequence_model_evaluation.csv`](tables/sequence_model_evaluation.csv) compares held-out first-order transitions with hero, phase, and purchase-position popularity baselines.
- [`state_overlap_diagnostics.csv`](tables/state_overlap_diagnostics.csv) reports coverage, Kish effective support, and maximum standardization weight for every hero/tier/item cell.
- [`outcome_confounding_correlations.csv`](tables/outcome_confounding_correlations.csv) quantifies the raw outcome relationship with cost, time, net worth, and adoption before and after tier stratification.
- [`hero_duration_profiles.csv`](tables/hero_duration_profiles.csv) records all-hero outcome sensitivity by game-ending interval.
- [`match_bootstrap_intervals.csv`](tables/match_bootstrap_intervals.csv) records reproducible uncertainty intervals for the ten most-adopted items in every hero/tier cell.
- [`hero_ability_scaling.csv`](tables/hero_ability_scaling.csv) records source-backed scaling channels for all 152 signature abilities.

The experimental paths assume nine base slots, no flex slots, at most four active items, component consumption, and explicit low-tier sells when necessary. They are inspectable research outputs—not Steam builds.

## Representative hero case studies

The ridge-adjusted rows and paths below are retained to make the rejected model's failure mode inspectable; they are comparisons, not recommendations. The adoption method is the current core-selection baseline.

{cases}

## Limitations

- Item choice is not randomized. Even state-standardized associations retain unmeasured skill, role, positioning, objective, and composition confounding.
- Match bootstrap intervals account for match sampling but not repeated-player clustering because public account identifiers are deliberately not persisted. Aggregate unique-account counts show that player-level dependence is nontrivial.
- Opening purchases often precede the first net-worth snapshot.
- Match-end win rate by duration describes games ending in that duration bucket; it is not a live hero power curve.
- Matchup cells are shrunk, main-effect-adjusted descriptive residuals—not causal effects. A counter claim still requires a defensible tactical mechanism, support, overlap, and temporal stability.
- The configured ceiling is Eternus V, but this post-reset sample has no observed average badge above 99. Ascendant- and Eternus-specific conclusions require later data.
- Current-rank results should not be combined with pre-reset numeric badges without a separately labeled sensitivity analysis.

## Reproduction

```bash
cd {paths.root}
uv run deadlock-build-sync refresh-evidence --run-id {paths.run.name}
```

Source endpoints and hashes are recorded under [`raw/`](raw/). Producer code identity
is captured before and after the run; Steam data is never accessed or mutated.

[^wilson]: Wilson intervals describe uncertainty around a binomial proportion; they do not correct selection bias.
[^eb]: Empirical Bayes borrows strength across related cells but remains dependent on the chosen pooling group and likelihood.
"""
    target = paths.run / "REPORT.md"
    target.write_text(report, encoding="utf-8")
    return {"report": str(target), "figures": len(list(paths.figures.glob("*.png")))}
