"""Train QDFM and evaluate frozen policies on later, untouched matches."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

import numpy as np
import torch

from experiments.qdfm.evaluate import (
    behavior_diagnostics,
    fitted_evaluation,
    hero_results,
    initial_values,
    load_fold,
    probabilities,
)
from experiments.qdfm.extract import fingerprint
from experiments.qdfm.model import Config, Flow, Network, train


def validate_dataset_identity(output: Path, expected: str) -> None:
    marker = output / "dataset.sha256"
    if marker.exists() and marker.read_text().strip() != expected:
        raise ValueError("Output directory belongs to a different frozen dataset")
    if (output / "models.pt").exists() and not marker.exists():
        raise ValueError(
            "Checkpoint has no dataset identity; use a fresh output directory"
        )
    marker.write_text(expected + "\n")


def run(directory: Path, output: Path, seed: int) -> None:
    torch.set_num_threads(2)
    output.mkdir(parents=True, exist_ok=True)
    config = Config(
        behavior_steps=3000,
        warmup_steps=2500,
        critic_steps=6000,
        improve_steps=1500,
        support_size=8,
        seed=seed,
    )
    validate_dataset_identity(output, fingerprint(directory / "dataset.json"))
    completed = output / "report.json"
    if completed.exists():
        report = json.loads(completed.read_text())
        if report["config"] != asdict(config) or report["model_sha256"] != fingerprint(
            output / "models.pt"
        ):
            raise ValueError("Completed run configuration or checkpoint does not match")
        print(completed, flush=True)
        return
    metadata = json.loads((directory / "dataset.json").read_text())
    for name, expected_hash in metadata["sha256"].items():
        if fingerprint(directory / name) != expected_hash:
            raise ValueError(f"Dataset file changed: {name}")
    folds = {
        name: load_fold(str(directory / f"{name}.npz"))
        for name in ("train", "validation", "test")
    }
    data = folds["train"].transitions
    checkpoint = output / "models.pt"
    if checkpoint.exists():
        if json.loads((output / "config.json").read_text()) != asdict(config):
            raise ValueError("Existing checkpoint has a different configuration")
        weights = torch.load(checkpoint, weights_only=True, map_location="cpu")
        behavior = Network(data.states.shape[1], data.masks.shape[1], config.hidden)
        critic = Network(data.states.shape[1], data.masks.shape[1], config.hidden)
        unweighted = Flow(data.states.shape[1], data.masks.shape[1], config.hidden)
        flow = Flow(data.states.shape[1], data.masks.shape[1], config.hidden)
        for name, model in (
            ("behavior", behavior),
            ("critic", critic),
            ("unweighted", unweighted),
            ("qdfm", flow),
        ):
            model.load_state_dict(weights[name])
            model.eval()
    else:
        behavior, critic, unweighted, flow = train(data, config)
        torch.save(
            {
                name: model.state_dict()
                for name, model in (
                    ("behavior", behavior),
                    ("critic", critic),
                    ("unweighted", unweighted),
                    ("qdfm", flow),
                )
            },
            checkpoint,
        )
        (output / "config.json").write_text(json.dumps(asdict(config), indent=2) + "\n")
    torch.manual_seed(seed + 10000)
    diagnostics = {
        name: behavior_diagnostics(behavior, folds[name])
        for name in ("validation", "test")
    }
    estimates = {}
    for name, policy in (
        ("behavior", None),
        ("unweighted", unweighted),
        ("qdfm", flow),
    ):
        print(f"Evaluating frozen {name} policy…", flush=True)
        cached = output / f"fqe-{name}.pt"
        # Recompute all evaluation stages after an interruption so the RNG
        # sequence matches an uninterrupted run, regardless of partial caches.
        next_probs = probabilities(
            behavior, policy, data.next_states, data.next_masks, config, samples=32
        )
        evaluator = fitted_evaluation(data, next_probs, config)
        torch.save(evaluator.state_dict(), cached)
        del next_probs
        estimates[name] = {
            fold: initial_values(evaluator, behavior, policy, folds[fold], config)
            for fold in ("validation", "test")
        }
    report = {
        "config": asdict(config),
        "dataset_sha256": fingerprint(directory / "dataset.json"),
        "model_sha256": fingerprint(checkpoint),
        "behavior_diagnostics": diagnostics,
        "evaluation": {},
        "promotion": False,
        "limitations": metadata["limitations"]
        + [
            "FQE is model-based and assumes sufficient observed state and action support.",
            "Intervals capture held-out sampling variation only, not confounding or model bias.",
            "Policy probabilities are approximated with 32 samples for FQE training and 256 for evaluation.",
            "This is a reduced-budget reproduction, not the authors' benchmark implementation.",
        ],
    }
    for fold in ("validation", "test"):
        indices, baseline = estimates["behavior"][fold]
        report["evaluation"][fold] = hero_results(
            folds[fold],
            indices,
            baseline,
            estimates["qdfm"][fold][1],
            metadata["episodes"],
        )
        np.savez_compressed(
            output / f"{fold}-initial-values.npz",
            indices=indices,
            behavior=baseline,
            unweighted=estimates["unweighted"][fold][1],
            qdfm=estimates["qdfm"][fold][1],
        )
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    run(args.directory, args.output, args.seed)
