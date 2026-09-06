"""Shared observed-state diagnostics, not counterfactual policy evaluation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
import torch
from torch import Tensor
from torch.nn import functional

from tools.comparisons.qdfm.actor_ablation import local_counts
from tools.comparisons.qdfm.algorithms import EULER, Learner, selected
from tools.comparisons.qdfm.evaluate import Fold, load_fold
from tools.comparisons.qdfm.extract import fingerprint
from tools.comparisons.qdfm.model import Network, masked_probs
from tools.comparisons.qdfm.toy import success

if TYPE_CHECKING:
    from pathlib import Path


@dataclass
class Cases:
    rows: list[dict]
    states: Tensor
    broad_masks: Tensor
    masks: Tensor
    supported: Tensor
    counts: Tensor
    neighbors: Tensor
    original_behavior: Tensor
    build_behavior: Tensor


@torch.no_grad()
def greedy_toy_score(model: Learner) -> float:
    """Evaluate displayed top choices.

    Returns:
        Exact expected success in the synthetic environment.

    """
    scores = []
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
            actions = model.policy(states, masks).argmax(dim=1)
            first = int(actions[0])
            scores.append(success(wealth, threat, first, int(actions[first + 1])))
    return sum(scores) / len(scores)


@torch.no_grad()
def frozen_behavior(
    states: Tensor, broad: Tensor, masks: Tensor, manifest: dict, runs: Path
) -> tuple[Tensor, Tensor]:
    original, build = [], []
    for checkpoint in manifest["checkpoints"]:
        path = runs / f"seed-{checkpoint['seed']}" / "models.pt"
        if fingerprint(path) != checkpoint["model_sha256"]:
            raise ValueError("Original behavior checkpoint changed")
        network = Network(
            states.shape[1], masks.shape[1], checkpoint["config"]["hidden"]
        )
        network.load_state_dict(
            torch.load(path, weights_only=True, map_location="cpu")["behavior"]
        )
        logits = network(states)
        original.append(masked_probs(logits, broad))
        restricted = torch.zeros_like(logits)
        active = masks.any(dim=1)
        restricted[active] = masked_probs(logits[active], masks[active])
        build.append(restricted)
    return torch.stack(original).mean(dim=0), torch.stack(build).mean(dim=0)


def load_cases(
    directory: Path, previews: Path, old_runs: Path
) -> tuple[Cases, Fold, dict]:
    metadata = json.loads((directory / "dataset.json").read_text())
    for name in ("train.npz", "validation.npz"):
        if fingerprint(directory / name) != metadata["sha256"][name]:
            raise ValueError("Frozen dataset changed")
    manifest = json.loads((previews / "manifest.json").read_text())
    if manifest["dataset_sha256"] != fingerprint(directory / "dataset.json"):
        raise ValueError("Preview dataset mismatch")
    rows = json.loads((previews / "examples.json").read_text())
    train = load_fold(str(directory / "train.npz"))
    validation = load_fold(str(directory / "validation.npz"))
    indices = [row["validation_row"] for row in rows]
    states = validation.transitions.states[indices]
    broad = validation.transitions.masks[indices]
    pools = {
        (pool["hero_id"], pool["path_id"]): {item["item_id"] for item in pool["items"]}
        for pool in manifest["pools"]
    }
    masks = broad & torch.tensor([
        [
            bool(action["item_ids"])
            and set(action["item_ids"]) <= pools[row["hero_id"], row["path_id"]]
            for action in metadata["actions"]
        ]
        for row in rows
    ])
    support = {
        index: local_counts(
            train,
            metadata,
            validation.transitions.states[index],
            int(validation.hero_ids[index]),
        )
        for index in sorted(set(indices))
    }
    counts = torch.from_numpy(np.stack([support[index][0] for index in indices]))
    neighbors = torch.tensor([support[index][1] for index in indices])
    supported = masks & (counts >= 5) & (neighbors[:, None] >= 50)
    original, build = frozen_behavior(states, broad, masks, manifest, old_runs)
    return (
        Cases(
            rows, states, broad, masks, supported, counts, neighbors, original, build
        ),
        validation,
        metadata,
    )


@torch.no_grad()
def validation_diagnostics(model: Learner, fold: Fold) -> dict:
    data = fold.transitions
    correct, losses, logged_q, gaps = [], [], [], []
    for offset in range(0, len(data.actions), 512):
        states = data.states[offset : offset + 512]
        masks = data.masks[offset : offset + 512]
        actions = data.actions[offset : offset + 512]
        probs = model.policy(states, masks)
        if not bool(torch.isfinite(probs).all()) or bool((probs[~masks] != 0).any()):
            raise ValueError("Invalid validation policy probabilities")
        correct.append(probs.argmax(dim=1) == actions)
        if model.config.method != "cql":
            logits = model.actor(states).masked_fill(~masks, -torch.inf)
            losses.append(functional.cross_entropy(logits, actions, reduction="none"))
        if model.config.method != "bc":
            logged_q.append(selected(model.minimum(states), actions))
        if model.config.method == "qql":
            gaps.append((model.value(states) - model.soft_value(states)).squeeze(1))
    matched = torch.cat(correct).float()
    result = {
        "rows": len(matched),
        "recorded_action_accuracy": float(matched.mean()),
        "recorded_action_nll": float(torch.cat(losses).mean()) if losses else None,
        "per_hero": {
            str(hero): {
                "rows": int((fold.hero_ids == hero).sum()),
                "recorded_action_accuracy": float(
                    matched[fold.hero_ids == hero].mean()
                ),
            }
            for hero in np.unique(fold.hero_ids)
        },
        "interpretation": "Imitation diagnostics; no policy outcome estimate",
    }
    if logged_q:
        values = torch.cat(logged_q)
        result["logged_action_q"] = {
            "minimum": float(values.min()),
            "mean": float(values.mean()),
            "maximum": float(values.max()),
        }
    if gaps:
        gap = torch.cat(gaps)
        temperature = model.config.qql_temperature_floor + gap.abs() / EULER
        result["qql_values"] = {
            "head_crossing_fraction": float((gap < 0).float().mean()),
            "gap_mean": float(gap.mean()),
            "temperature_minimum": float(temperature.min()),
            "temperature_median": float(temperature.median()),
            "temperature_maximum": float(temperature.max()),
        }
    return result
