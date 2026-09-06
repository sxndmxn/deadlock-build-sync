"""Render experimental recommendations at observed validation states."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import torch

from tools.comparisons.qdfm.evaluate import Fold, load_fold, probabilities
from tools.comparisons.qdfm.extract import HEROES
from tools.comparisons.qdfm.model import Config, Flow, Network


def selected_rows(fold: Fold) -> list[int]:
    """Select the same observed states for the broad and build-specific previews.

    Returns:
        Validation row indices, in hero and relative wealth order.

    """
    chosen = []
    for hero in HEROES:
        rows = np.flatnonzero(fold.hero_ids == hero)
        states = fold.transitions.states[rows]
        for percentile in (0.2, 0.5, 0.8):
            score = (states[:, 4] - percentile).square() + (
                (states[:, 0] * 2400 - 900) / 900
            ).square()
            chosen.append(int(rows[int(score.argmin())]))
    return chosen


def examples(directory: Path, runs: Path) -> list[dict[str, object]]:
    torch.set_num_threads(2)
    torch.manual_seed(947)
    metadata = json.loads((directory / "dataset.json").read_text())
    fold = load_fold(str(directory / "validation.npz"))
    chosen = selected_rows(fold)
    states, masks = fold.transitions.states[chosen], fold.transitions.masks[chosen]
    flow_probs, behavior_probs = [], []
    for seed in (42, 43, 44):
        run = runs / f"seed-{seed}"
        config = Config(**json.loads((run / "config.json").read_text()))
        weights = torch.load(run / "models.pt", weights_only=True, map_location="cpu")
        behavior = Network(states.shape[1], masks.shape[1], config.hidden)
        flow = Flow(states.shape[1], masks.shape[1], config.hidden)
        behavior.load_state_dict(weights["behavior"])
        flow.load_state_dict(weights["qdfm"])
        behavior_probs.append(probabilities(behavior, None, states, masks, config))
        flow_probs.append(
            probabilities(behavior, flow, states, masks, config, samples=1024)
        )
    avg_flow, avg_behavior = (
        torch.stack(flow_probs).mean(dim=0),
        torch.stack(behavior_probs).mean(dim=0),
    )
    results = []
    for index, row in enumerate(chosen):
        own_items = [
            name.removeprefix("owned:")
            for name, value in zip(metadata["features"], states[index], strict=True)
            if name.startswith("owned:") and value > 0
        ]
        top = avg_flow[index].topk(3).indices.tolist()
        results.append({
            "hero": HEROES[int(fold.hero_ids[row])][0],
            "group": HEROES[int(fold.hero_ids[row])][1],
            "time_s": int(fold.times[row]),
            "wealth": round(float(states[index, 1]) * 50000),
            "lobby_wealth_percentile": float(states[index, 4]),
            "relative_wealth_gap": float(states[index, 3]),
            "snapshot_age_s": round(float(states[index, 10]) * 300),
            "owned_items": own_items,
            "qdfm_targets": [
                {
                    "name": metadata["actions"][action]["name"],
                    "policy_probability": float(avg_flow[index, action]),
                    "behavior_probability": float(avg_behavior[index, action]),
                    "top1_seed_votes": sum(
                        int(probs[index].argmax()) == action for probs in flow_probs
                    ),
                }
                for action in top
            ],
            "historical_next_purchase": metadata["actions"][
                int(fold.transitions.actions[row])
            ]["name"],
            "label": "Research preview at a logged state; no affordability or build-identity guarantee.",
        })
    return results


def render(rows: list[dict[str, object]], output: Path) -> None:
    lines = [
        "# Experimental QDFM item targets",
        "",
        "Three observed validation states per hero, chosen near 15 minutes and low/middle/high lobby wealth ranks.",
        "These are research previews, not approved builds. Probabilities describe model choices, not chances of winning.",
        "The values average three training seeds. A basket joined by `+` is one simultaneous purchase action.",
        "",
    ]
    for row in rows:
        lines += [
            f"## {row['hero']} — {int(row['time_s']) // 60}:{int(row['time_s']) % 60:02d}",
            "",
            (
                f"Wealth: {row['wealth']:,}; lobby percentile: {float(row['lobby_wealth_percentile']):.0%}; "
                f"snapshot age: {row['snapshot_age_s']} seconds."
            ),
            "",
            "Owned: " + ", ".join(row["owned_items"]) + ".",
            "",
            "| Model target | QDFM probability | Behavior probability | Seeds ranking it first |",
            "| --- | ---: | ---: | ---: |",
        ]
        for choice in row["qdfm_targets"]:
            lines.append(
                f"| {choice['name']} | {choice['policy_probability']:.1%} | "
                f"{choice['behavior_probability']:.1%} | {choice['top1_seed_votes']}/3 |"
            )
        lines += ["", f"Recorded next purchase: {row['historical_next_purchase']}.", ""]
    output.mkdir(parents=True, exist_ok=True)
    (output / "examples.json").write_text(json.dumps(rows, indent=2) + "\n")
    (output / "examples.md").write_text("\n".join(lines))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--runs", required=True, type=Path)
    args = parser.parse_args()
    render(examples(args.directory, args.runs), args.runs)
