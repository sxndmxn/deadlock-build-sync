"""Summarize independent metrics and paired cluster resampling."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from .benchmark import summarize


def cluster_interval(
    differences: np.ndarray, groups: np.ndarray, resamples: int = 2000
) -> tuple[float, float, float]:
    _, indices = np.unique(groups, return_inverse=True)
    sums = np.bincount(indices, weights=differences)
    counts = np.bincount(indices)
    generator = np.random.default_rng(23)
    estimates = []
    for offset in range(0, resamples, 100):
        draws = generator.integers(
            0, len(counts), size=(min(100, resamples - offset), len(counts))
        )
        estimates.extend(sums[draws].sum(axis=1) / counts[draws].sum(axis=1))
    lower, upper = np.quantile(estimates, [0.025, 0.975])
    return float(np.mean(differences)), float(lower), float(upper)


def measure(row: dict[str, object], name: str) -> float:
    if name == "emitted":
        return float(bool(row["paths"]))
    if name.startswith("support_"):
        minimum = int(name.removeprefix("support_"))
        return float(
            bool(row["paths"])
            and (row["paths"][0]["heldout"]["owners"] or 0) >= minimum
        )
    return float(row[name])


def query_key(row: dict[str, object], mode: str) -> tuple[int, ...]:
    if mode == "decisions":
        return int(row["hero"]), int(row["match"])
    return int(row["hero"]), int(row["budget"]), int(row["relative_state"])


def paired_comparison(
    first: list[dict[str, object]],
    second: list[dict[str, object]],
    mode: str,
    metric: str,
) -> dict[str, object]:
    lookup = {query_key(row, mode): row for row in first}
    if len(lookup) != len(first) or set(lookup) != {
        query_key(row, mode) for row in second
    }:
        raise ValueError("Paired results must contain the same unique queries")
    differences = np.asarray([
        measure(row, metric) - measure(lookup[query_key(row, mode)], metric)
        for row in second
    ])
    groups = np.asarray([
        row["match" if mode == "decisions" else "hero"] for row in second
    ])
    mean, lower, upper = cluster_interval(differences, groups)
    return {
        "difference": mean,
        "lower_95": lower,
        "upper_95": upper,
        "clusters": len(np.unique(groups)),
        "cluster_unit": "match" if mode == "decisions" else "hero",
        "resamples": 2000,
        "seed": 23,
    }


def outcome_summary(records: list[dict[str, object]]) -> dict[str, object]:
    outcomes = [row["paths"][0]["heldout"] for row in records if row["paths"]]
    supported = [row for row in outcomes if (row["owners"] or 0) >= 30]
    differences = [row["win_rate"] - row["hero_win_rate"] for row in supported]
    widths = [row["upper_95"] - row["lower_95"] for row in supported]
    return {
        "supported_queries": len(supported),
        "raw_rate_above_hero": sum(value > 0 for value in differences),
        "median_raw_difference": float(np.median(differences)) if differences else None,
        "median_interval_width": float(np.median(widths)) if widths else None,
        "interpretation": "Descriptive associations. Query cohorts can overlap.",
    }


def analyze(document: dict[str, object]) -> dict[str, object]:
    mode = document["mode"]
    results = {
        row["config"]["method"] + ":" + str(row["config"]["width"]): row
        for row in document["results"]
    }
    metrics = (
        ("emitted", "top1_agreement", "alternative_agreement")
        if mode == "decisions"
        else ("emitted", "support_30", "support_100")
    )
    comparisons = {}
    for baseline in ("greedy:1", "beam:8", "beam:16"):
        if baseline not in results:
            continue
        for name, result in results.items():
            if name == baseline:
                continue
            comparisons[name + " minus " + baseline] = {
                metric: paired_comparison(
                    results[baseline]["records"], result["records"], mode, metric
                )
                for metric in metrics
            }
    return {
        "partition": document["partition"],
        "mode": mode,
        "paired_comparisons": comparisons,
        "outcomes": {
            name: outcome_summary(result["records"]) for name, result in results.items()
        }
        if mode == "guides"
        else {},
        "per_hero": {
            name: hero_summaries(result["records"], document["heroes"], mode)
            for name, result in results.items()
        },
    }


def hero_summaries(
    records: list[dict[str, object]], heroes: list[int], mode: str
) -> dict[str, object]:
    return {
        str(hero): summarize([row for row in records if row["hero"] == hero], mode)
        for hero in heroes
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze paired search results")
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    arguments = parser.parse_args()
    document = json.loads(arguments.input.read_text(encoding="utf-8"))
    arguments.output.write_text(
        json.dumps(analyze(document), indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
