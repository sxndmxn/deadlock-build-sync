"""Separate flow approximation, value guidance, and local purchase support."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import torch

from tools.comparisons.qdfm.evaluate import Fold, load_fold, probabilities
from tools.comparisons.qdfm.extract import fingerprint
from tools.comparisons.qdfm.model import Config, Flow, Network, masked_probs


def local_counts(
    train: Fold, metadata: dict, state: torch.Tensor, hero: int
) -> tuple[np.ndarray, int]:
    states = train.transitions.states
    owned_columns = [
        index
        for index, name in enumerate(metadata["features"])
        if name.startswith("owned:")
    ]
    owned = states[:, owned_columns] > 0
    query_owned = state[owned_columns] > 0
    intersection = (owned & query_owned).sum(dim=1)
    union = (owned | query_owned).sum(dim=1).clamp_min(1)
    selected = (
        torch.from_numpy(train.hero_ids == hero)
        & ((states[:, 0] - state[0]).abs() * 2400 <= 180)
        & ((states[:, 1] / state[1].clamp_min(0.02) - 1).abs() <= 0.35)
        & ((states[:, 4] - state[4]).abs() <= 0.25)
        & (intersection / union >= 0.4)
    ).numpy()
    episode_ids = train.episode_ids[selected]
    matches = np.array(
        [metadata["episodes"][int(episode)]["match_id"] for episode in episode_ids],
        dtype=np.int64,
    )
    actions = train.transitions.actions[selected].numpy()
    distinct = np.unique(np.column_stack((matches, actions)), axis=0)
    counts = np.bincount(distinct[:, 1], minlength=train.transitions.masks.shape[1])
    return counts, len(np.unique(matches))


def boltzmann(
    logits: torch.Tensor, values: torch.Tensor, masks: torch.Tensor, beta: float
) -> torch.Tensor:
    return masked_probs(logits + beta * values, masks)


def summary(
    probs: torch.Tensor,
    behavior: torch.Tensor,
    build_behavior: torch.Tensor,
    counts: torch.Tensor,
) -> dict:
    mean = probs.mean(dim=0)
    active = mean.sum(dim=1) > 0
    top = mean.argmax(dim=1)
    selected = torch.arange(len(top))[active]
    return {
        "rows": len(top),
        "abstentions": int((~active).sum()),
        "unanimous_top": int(((probs.argmax(dim=2) == top).all(dim=0) & active).sum()),
        "top_original_behavior_below_1pct": int(
            (behavior[selected, top[active]] < 0.01).sum()
        ),
        "top_local_matches_below_5": int((counts[selected, top[active]] < 5).sum()),
        "mean_total_variation_from_build_behavior": float(
            (0.5 * (mean[active] - build_behavior[active]).abs().sum(dim=1)).mean()
        ),
    }


def predict(
    states: torch.Tensor,
    broad_masks: torch.Tensor,
    masks: torch.Tensor,
    supported: torch.Tensor,
    manifest: dict,
    runs: Path,
) -> tuple[dict, torch.Tensor]:
    active = supported.any(dim=1)
    outputs = {
        name: []
        for name in (
            "behavior",
            "unweighted_flow",
            "qdfm",
            "direct_Q_beta5",
            "supported_qdfm",
            "supported_direct_Q_beta5",
        )
    }
    original_behavior = []
    for saved in manifest["checkpoints"]:
        seed = saved["seed"]
        path = runs / f"seed-{seed}"
        if fingerprint(path / "models.pt") != saved["model_sha256"]:
            raise ValueError("Frozen checkpoint changed")
        config = Config(**saved["config"])
        weights = torch.load(path / "models.pt", weights_only=True, map_location="cpu")
        behavior = Network(states.shape[1], masks.shape[1], config.hidden)
        critic = Network(states.shape[1], masks.shape[1], config.hidden)
        behavior.load_state_dict(weights["behavior"])
        critic.load_state_dict(weights["critic"])
        with torch.no_grad():
            logits, values = behavior(states), critic(states).sigmoid()
            original_behavior.append(masked_probs(logits, broad_masks))
            outputs["behavior"].append(masked_probs(logits, masks))
            outputs["direct_Q_beta5"].append(boltzmann(logits, values, masks, 5))
            supported_direct = torch.zeros_like(logits)
            if active.any():
                supported_direct[active] = boltzmann(
                    logits[active], values[active], supported[active], 5
                )
            outputs["supported_direct_Q_beta5"].append(supported_direct)
        for name, checkpoint in (
            ("unweighted_flow", "unweighted"),
            ("qdfm", "qdfm"),
            ("supported_qdfm", "qdfm"),
        ):
            flow = Flow(states.shape[1], masks.shape[1], config.hidden)
            flow.load_state_dict(weights[checkpoint])
            selected_mask = supported if name == "supported_qdfm" else masks
            selected = selected_mask.any(dim=1)
            prediction = torch.zeros_like(logits)
            torch.manual_seed(seed + 947)
            if selected.any():
                prediction[selected] = probabilities(
                    behavior,
                    flow,
                    states[selected],
                    selected_mask[selected],
                    config,
                    samples=512,
                )
            outputs[name].append(prediction)
        print(f"Ablation seed {seed} complete", flush=True)
    outputs = {name: torch.stack(values) for name, values in outputs.items()}
    original = torch.stack(original_behavior).mean(dim=0)
    return outputs, original


def example_rows(
    rows: list[dict],
    outputs: dict,
    metadata: dict,
    counts: torch.Tensor,
    neighbors: torch.Tensor,
    original: torch.Tensor,
) -> list[dict]:
    examples = []
    for index, row in enumerate(rows):
        choices = {}
        for name, predictions in outputs.items():
            average = predictions[:, index].mean(dim=0)
            action = int(average.argmax())
            choices[name] = (
                None
                if average.sum() == 0
                else {
                    "name": metadata["actions"][action]["name"],
                    "probability": float(average[action]),
                    "local_distinct_matches": int(counts[index, action]),
                    "original_behavior_probability": float(original[index, action]),
                }
            )
        examples.append({
            "hero": row["hero"],
            "path_label": row["path_label"],
            "time_s": row["time_s"],
            "wealth_percentile": row["lobby_wealth_percentile"],
            "neighbor_matches": int(neighbors[index]),
            "choices": choices,
        })
    return examples


def run(directory: Path, runs: Path, previews: Path, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    torch.set_num_threads(2)
    metadata = json.loads((directory / "dataset.json").read_text())
    for fold in ("train", "validation"):
        if fingerprint(directory / f"{fold}.npz") != metadata["sha256"][f"{fold}.npz"]:
            raise ValueError("Frozen dataset changed")
    rows = json.loads((previews / "examples.json").read_text())
    manifest = json.loads((previews / "manifest.json").read_text())
    if manifest["dataset_sha256"] != fingerprint(directory / "dataset.json"):
        raise ValueError("Preview belongs to another dataset")
    validation = load_fold(str(directory / "validation.npz"))
    train = load_fold(str(directory / "train.npz"))
    indices = [row["validation_row"] for row in rows]
    states = validation.transitions.states[indices]
    broad_masks = validation.transitions.masks[indices]
    pools = {
        (p["hero_id"], p["path_id"]): {i["item_id"] for i in p["items"]}
        for p in manifest["pools"]
    }
    masks = broad_masks & torch.tensor([
        [
            set(action["item_ids"]) <= pools[row["hero_id"], row["path_id"]]
            for action in metadata["actions"]
        ]
        for row in rows
    ])
    support_cache = {
        index: local_counts(
            train,
            metadata,
            validation.transitions.states[index],
            int(validation.hero_ids[index]),
        )
        for index in sorted(set(indices))
    }
    counts = torch.from_numpy(np.stack([support_cache[index][0] for index in indices]))
    neighbors = torch.tensor([support_cache[index][1] for index in indices])
    supported = masks & (counts >= 5) & (neighbors[:, None] >= 50)
    outputs, original = predict(states, broad_masks, masks, supported, manifest, runs)
    summaries = {
        name: summary(values, original, outputs["behavior"].mean(dim=0), counts)
        for name, values in outputs.items()
    }
    examples = example_rows(rows, outputs, metadata, counts, neighbors, original)
    report = {
        "summaries": summaries,
        "examples": examples,
        "promotion": False,
        "script_sha256": fingerprint(Path(__file__)),
        "source_preview_manifest_sha256": fingerprint(previews / "manifest.json"),
        "local_support": {
            "train_only": True,
            "time_caliper_s": 180,
            "relative_wealth_caliper": 0.35,
            "percentile_caliper": 0.25,
            "inventory_jaccard_min": 0.4,
            "minimum_distinct_matches_per_action": 5,
            "minimum_neighbor_matches": 50,
        },
        "support_sensitivity": {
            str(threshold): {
                "rows_with_any_supported_action": int(
                    (masks & (counts >= threshold) & (neighbors[:, None] >= 50))
                    .any(dim=1)
                    .sum()
                )
            }
            for threshold in (3, 5, 10)
        },
        "unweighted_vs_behavior_mean_tv": float(
            (
                0.5
                * (
                    outputs["unweighted_flow"].mean(dim=0)
                    - outputs["behavior"].mean(dim=0)
                )
                .abs()
                .sum(dim=1)
            ).mean()
        ),
        "qdfm_vs_direct_Q_mean_tv": float(
            (
                0.5
                * (outputs["qdfm"].mean(dim=0) - outputs["direct_Q_beta5"].mean(dim=0))
                .abs()
                .sum(dim=1)
            ).mean()
        ),
        "limitations": [
            "57 path/state previews reuse 27 validation states",
            "No new outcome evaluation or retraining",
            "Local support is plausibility evidence, not a counter effectiveness estimate",
            "Build-restricted inference uses originally hero-wide values",
        ],
    }
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(summaries, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--runs", required=True, type=Path)
    parser.add_argument("--previews", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    run(args.directory, args.runs, args.previews, args.output)
