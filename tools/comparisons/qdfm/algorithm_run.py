"""Train the predeclared alternative algorithms without touching Steam."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

import torch

from tools.comparisons.qdfm.algorithms import METHODS, AlgorithmConfig, Learner, fit
from tools.comparisons.qdfm.evaluate import load_fold
from tools.comparisons.qdfm.extract import fingerprint
from tools.comparisons.qdfm.toy import make_data, success


@torch.no_grad()
def toy_outcome(model: Learner) -> dict:
    contexts = []
    for wealth in (0, 1):
        for threat in (0, 1):
            states = torch.tensor([
                [wealth, threat, 0, 0, 0],
                [wealth, threat, 1, 1, 0],
                [wealth, threat, 1, 0, 1],
            ]).float()
            masks = torch.tensor([
                [True, True, False, False],
                [False, False, True, True],
                [False, False, True, True],
            ])
            probs = model.policy(states, masks)
            expected = sum(
                float(probs[0, first] * probs[first + 1, second])
                * success(wealth, threat, first, second)
                for first in (0, 1)
                for second in (2, 3)
            )
            contexts.append({
                "ahead": bool(wealth),
                "heavy_threat": bool(threat),
                "defense_probability": float(probs[0, 0]),
                "compatible_continuation_probability": [
                    float(probs[1, 2]),
                    float(probs[2, 3]),
                ],
                "true_expected_success": expected,
            })
    return {
        "optimal_success": 0.8,
        "mean_true_expected_success": sum(
            row["true_expected_success"] for row in contexts
        )
        / len(contexts),
        "contexts": contexts,
    }


def write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )


def run(directory: Path, output: Path, seed: int) -> None:
    torch.set_num_threads(1)
    metadata = json.loads((directory / "dataset.json").read_text())
    if fingerprint(directory / "train.npz") != metadata["sha256"]["train.npz"]:
        raise ValueError("Frozen training data changed")
    destination = output / f"seed-{seed}"
    destination.mkdir(parents=True, exist_ok=False)
    source = Path(__file__).parent
    provenance = {
        "dataset_sha256": fingerprint(directory / "dataset.json"),
        "train_sha256": fingerprint(directory / "train.npz"),
        "seed": seed,
        "torch_version": str(torch.__version__),
        "source_sha256": {
            name: fingerprint(source / name)
            for name in (
                "algorithms.py",
                "algorithm_run.py",
                "model.py",
                "toy.py",
                "ALGORITHMS.md",
            )
        },
    }
    write_json(destination / "provenance.json", provenance)
    toy = make_data(seed)
    train = load_fold(str(directory / "train.npz")).transitions
    for method in METHODS:
        folder = destination / method
        folder.mkdir()
        toy_config = AlgorithmConfig(method=method, seed=seed, hidden=64, steps=3000)
        model, history = fit(toy, toy_config)
        write_json(
            folder / "toy.json",
            {"config": asdict(toy_config), "history": history, **toy_outcome(model)},
        )
        torch.save(model.state_dict(), folder / "toy.pt")
        config = AlgorithmConfig(method=method, seed=seed)
        model, history = fit(train, config)
        torch.save(model.state_dict(), folder / "model.pt")
        write_json(
            folder / "report.json",
            {
                "config": asdict(config),
                "history": history,
                "model_sha256": fingerprint(folder / "model.pt"),
                "toy_model_sha256": fingerprint(folder / "toy.pt"),
                "toy_report_sha256": fingerprint(folder / "toy.json"),
                "provenance_sha256": fingerprint(destination / "provenance.json"),
            },
        )
        print(f"Completed {method} seed={seed}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    run(args.directory, args.output, args.seed)
