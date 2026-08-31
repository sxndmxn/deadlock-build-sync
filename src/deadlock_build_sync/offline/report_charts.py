from __future__ import annotations

import matplotlib as mpl
import numpy as np
import polars as pl

from .config import RunPaths
from .report_helpers import _weighted_evaluation

mpl.use("Agg")
import matplotlib.pyplot as plt


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
