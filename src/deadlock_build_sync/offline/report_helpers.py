from __future__ import annotations

import numpy as np
import polars as pl

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
