"""Compare new algorithms on the frozen previews and known-outcome toy."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import TYPE_CHECKING

import torch

from experiments.qdfm.actor_ablation import example_rows, summary
from experiments.qdfm.algorithm_diagnostics import (
    greedy_toy_score,
    load_cases,
    validation_diagnostics,
)
from experiments.qdfm.algorithm_run import write_json
from experiments.qdfm.algorithms import METHODS, AlgorithmConfig, Learner
from experiments.qdfm.extract import fingerprint

if TYPE_CHECKING:
    from experiments.qdfm.algorithm_diagnostics import Cases


def load_model(
    runs: Path, method: str, seed: int, shape: tuple[int, int], identity: str
) -> tuple[Learner, dict, dict]:
    root = runs / f"seed-{seed}"
    provenance = json.loads((root / "provenance.json").read_text())
    if provenance["dataset_sha256"] != identity or provenance["seed"] != seed:
        raise ValueError("Alternative checkpoint belongs to another dataset/seed")
    for name, expected in provenance["source_sha256"].items():
        if fingerprint(Path(__file__).parent / name) != expected:
            raise ValueError(f"Training source changed since this run: {name}")
    folder = root / method
    report = json.loads((folder / "report.json").read_text())
    for name, key in (
        ("model.pt", "model_sha256"),
        ("toy.pt", "toy_model_sha256"),
        ("toy.json", "toy_report_sha256"),
    ):
        if fingerprint(folder / name) != report[key]:
            raise ValueError("Alternative checkpoint/report changed")
    if fingerprint(root / "provenance.json") != report["provenance_sha256"]:
        raise ValueError("Checkpoint provenance changed")
    config = AlgorithmConfig(**report["config"])
    if config.method != method or config.seed != seed:
        raise ValueError("Checkpoint configuration mismatch")
    model = Learner(*shape, config)
    model.load_state_dict(
        torch.load(folder / "model.pt", weights_only=True, map_location="cpu")
    )
    if not all(
        bool(torch.isfinite(value).all()) for value in model.state_dict().values()
    ):
        raise ValueError("Nonfinite trained model")
    toy_result = json.loads((folder / "toy.json").read_text())
    toy_config = AlgorithmConfig(**toy_result["config"])
    toy_model = Learner(5, 4, toy_config)
    toy_model.load_state_dict(
        torch.load(folder / "toy.pt", weights_only=True, map_location="cpu")
    )
    toy_result["supplementary_greedy_top1_success"] = greedy_toy_score(toy_model.eval())
    return model.eval(), report, toy_result


def render(report: dict, output: Path) -> None:
    lines = [
        "# Alternative algorithm pilot",
        "",
        "Three seeds; frozen training data; 57 path/state previews reuse 27 validation states.",
        "These are purchase plausibility and stability diagnostics, not Deadlock win-rate estimates.",
        "Every new method uses 6,000 minibatch iterations; computational work per iteration differs.",
        "CQL uses a greedy policy; the other new methods use exact categorical probabilities.",
        "",
        "## Known-outcome two-purchase task",
        "",
        "Exact policy expectation in the synthetic environment; optimum 80%. Each new run uses 3,000 iterations.",
        "",
        "| Method | Seed 42 | Seed 43 | Seed 44 |",
        "| --- | ---: | ---: | ---: |",
    ]
    for method, runs in report["toy"].items():
        cells = " | ".join(f"{run['mean_true_expected_success']:.1%}" for run in runs)
        lines.append(f"| {method} | {cells} |")
    lines += [
        "",
        "Supplement added after the initial comparison: choosing the top action at both stages removes the stochastic-versus-greedy extraction difference. No retraining or parameter selection.",
        "",
        "| Greedy top-choice policy | Seed 42 | Seed 43 | Seed 44 |",
        "| --- | ---: | ---: | ---: |",
    ]
    for method, runs in report["toy"].items():
        cells = " | ".join(
            f"{run['supplementary_greedy_top1_success']:.1%}" for run in runs
        )
        lines.append(f"| {method} | {cells} |")
    lines += [
        "",
        "## Deadlock preview diagnostics",
        "",
        "Rare choices have under 1% probability in the original broad BC model. Sparse choices have fewer than five local training matches.",
        "Support gate: at least 50 neighbor matches and five matches for a candidate action; otherwise abstain.",
        "Agreement counts require all three seeds to choose the same top action. Sparse/rare counts refer to the ensemble's top choice.",
        "",
        "| Method | All-seed agreement | Rare choice | Sparse choice | Abstentions | TV from original build BC |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for method, row in report["summaries"].items():
        lines.append(
            f"| {method} | {row['unanimous_top']}/{row['rows']} | {row['top_original_behavior_below_1pct']} | {row['top_local_matches_below_5']} | {row['abstentions']} | {row['mean_total_variation_from_build_behavior']:.3f} |"
        )
    lines += [
        "",
        "## Whole-validation imitation diagnostics",
        "",
        "Top-action accuracy across 19,795 recorded decisions, by seed; this is not a policy-quality ranking.",
        "",
        "| Method | Seed 42 | Seed 43 | Seed 44 |",
        "| --- | ---: | ---: | ---: |",
    ]
    for method, runs in report["validation"].items():
        cells = " | ".join(f"{run['recorded_action_accuracy']:.1%}" for run in runs)
        lines.append(f"| {method} | {cells} |")
    lines += [
        "",
        "## All build/state choices",
        "",
        "Pooled probabilities describe model choices. Different build selections reuse the same historical state; future purchases do not select a path.",
        "",
        "| Hero | Build | Wealth percentile | Neighbor matches | BC | IQL | CQL | QQL | Supported IQL | Supported QQL |",
        "| --- | --- | ---: | ---: | --- | --- | --- | --- | --- | --- |",
    ]
    for row in report["examples"]:
        choices = []
        for method in ("bc", "iql", "cql", "qql", "supported_iql", "supported_qql"):
            choice = row["choices"][method]
            choices.append("abstain" if choice is None else choice["name"])
        lines.append(
            f"| {row['hero']} | {row['path_label']} | {row['wealth_percentile']:.0%} | {row['neighbor_matches']} | "
            + " | ".join(choices)
            + " |"
        )
    lines += ["", "## Limits", ""] + [f"- {item}" for item in report["limitations"]]
    (output / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def compare_previews(cases: Cases, predictions: dict) -> tuple[dict, dict, dict]:
    for name, values in predictions.items():
        masks = cases.supported if name.startswith("supported_") else cases.masks
        if not bool(torch.isfinite(values).all()) or bool(
            (values[:, ~masks] != 0).any()
        ):
            raise ValueError("Preview emitted an invalid or off-pool probability")
    summaries = {
        name: summary(
            values, cases.original_behavior, cases.build_behavior, cases.counts
        )
        for name, values in predictions.items()
    }
    bc_mean = predictions["bc"].mean(dim=0)
    comparisons = {
        method: {
            "top_choices_different_from_new_bc": int(
                (values.mean(dim=0).argmax(dim=1) != bc_mean.argmax(dim=1)).sum()
            ),
            "mean_total_variation_from_new_bc": float(
                (0.5 * (values.mean(dim=0) - bc_mean).abs().sum(dim=1)).mean()
            ),
        }
        for method, values in predictions.items()
        if not method.startswith("supported_")
    }
    hero_summaries = {}
    for hero in dict.fromkeys(row["hero"] for row in cases.rows):
        selected_rows = torch.tensor([row["hero"] == hero for row in cases.rows])
        hero_summaries[hero] = {
            "group": next(row["group"] for row in cases.rows if row["hero"] == hero),
            "supported_rows": int(cases.supported[selected_rows].any(dim=1).sum()),
            "methods": {
                method: summary(
                    predictions[method][:, selected_rows],
                    cases.original_behavior[selected_rows],
                    cases.build_behavior[selected_rows],
                    cases.counts[selected_rows],
                )
                for method in METHODS
            },
        }
    return summaries, comparisons, hero_summaries


def run(directory: Path, runs: Path, previews: Path, old_runs: Path) -> None:
    torch.set_num_threads(2)
    cases, validation, metadata = load_cases(directory, previews, old_runs)
    identity = fingerprint(directory / "dataset.json")
    outputs, toy, diagnostics, checkpoints = {}, {}, {}, []
    for method in METHODS:
        outputs[method], outputs[f"supported_{method}"] = [], []
        toy[method], diagnostics[method] = [], []
        for seed in (42, 43, 44):
            model, saved, toy_result = load_model(
                runs,
                method,
                seed,
                (cases.states.shape[1], cases.masks.shape[1]),
                identity,
            )
            outputs[method].append(model.policy(cases.states, cases.masks))
            outputs[f"supported_{method}"].append(
                model.policy(cases.states, cases.supported)
            )
            toy[method].append(toy_result)
            diagnostics[method].append(validation_diagnostics(model, validation))
            checkpoints.append({"method": method, "seed": seed, **saved})
            print(f"Reviewed {method} seed={seed}", flush=True)
    predictions = {name: torch.stack(values) for name, values in outputs.items()}
    summaries, comparisons, hero_summaries = compare_previews(cases, predictions)
    torch.save(predictions, runs / "preview_probabilities.pt")
    baseline = old_runs / "actor-ablation" / "report.json"
    previous = json.loads(baseline.read_text())
    if previous["source_preview_manifest_sha256"] != fingerprint(
        previews / "manifest.json"
    ):
        raise ValueError("Previous flow diagnostic used different previews")
    report = {
        "promotion": False,
        "dataset_sha256": identity,
        "preview_manifest_sha256": fingerprint(previews / "manifest.json"),
        "preview_examples_sha256": fingerprint(previews / "examples.json"),
        "source_sha256": {
            name: fingerprint(Path(__file__).parent / name)
            for name in (
                "algorithm_review.py",
                "algorithm_diagnostics.py",
                "actor_ablation.py",
            )
        },
        "checkpoints": checkpoints,
        "toy": toy,
        "summaries": summaries,
        "comparison_to_new_bc": comparisons,
        "per_hero": hero_summaries,
        "preview_probabilities_sha256": fingerprint(runs / "preview_probabilities.pt"),
        "validation": diagnostics,
        "examples": example_rows(
            cases.rows,
            predictions,
            metadata,
            cases.counts,
            cases.neighbors,
            cases.original_behavior,
        ),
        "previous_flow_diagnostics": {
            "report_sha256": fingerprint(baseline),
            "summaries": previous["summaries"],
        },
        "limitations": [
            "No counterfactual Deadlock outcome evaluation; own critic outputs are not win rates.",
            "New training budgets/configurations differ from the previous QDFM pilot; these are adaptations, not paper leaderboard comparisons.",
            "Three seeds and 57 selected previews are a small debugging sample; 57 previews are not 57 independent matches.",
            "The same original BC and local-support definition are used for every new method.",
            "Build evidence overlaps the validation period; validation metrics are exploratory.",
            "Models train hero-wide and apply build pools at inference, without enforced continuation within that build.",
            "Pool membership does not enforce core order, counter triggers, pair compatibility, affordability, slots, or waiting.",
            "Dataset selection, partial observations, confounding, and sparse action overlap remain unchanged.",
            "No new test-fold evaluation or Steam publication.",
        ],
    }
    write_json(runs / "report.json", report)
    render(report, runs)
    print(json.dumps(summaries, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--runs", required=True, type=Path)
    parser.add_argument("--previews", required=True, type=Path)
    parser.add_argument("--old-runs", required=True, type=Path)
    args = parser.parse_args()
    run(args.directory, args.runs, args.previews, args.old_runs)
