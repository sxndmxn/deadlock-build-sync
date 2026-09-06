"""Generate local build-restricted previews with the frozen, hero-wide models."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import torch

from tools.comparisons.qdfm.build_pool import BuildPool, load_pools
from tools.comparisons.qdfm.evaluate import load_fold, probabilities
from tools.comparisons.qdfm.extract import HEROES, fingerprint
from tools.comparisons.qdfm.model import Config, Flow, Network
from tools.comparisons.qdfm.review import selected_rows


def frozen_predictions(
    directory: Path,
    runs: Path,
    states: torch.Tensor,
    broad_masks: torch.Tensor,
    restricted_masks: torch.Tensor,
) -> tuple[list[torch.Tensor], list[torch.Tensor], list[torch.Tensor], list[dict]]:
    broad, restricted, behavior_probs, checkpoints = [], [], [], []
    active = restricted_masks.any(dim=1)
    identity = fingerprint(directory / "dataset.json")
    for seed in (42, 43, 44):
        run = runs / f"seed-{seed}"
        if (run / "dataset.sha256").read_text().strip() != identity:
            raise ValueError("Frozen checkpoint belongs to a different dataset")
        config = Config(**json.loads((run / "config.json").read_text()))
        checkpoint_hash = fingerprint(run / "models.pt")
        report = json.loads((run / "report.json").read_text())
        if (
            report["model_sha256"] != checkpoint_hash
            or report["config"] != json.loads((run / "config.json").read_text())
            or config.seed != seed
        ):
            raise ValueError(
                "Frozen checkpoint/configuration no longer matches its report"
            )
        weights = torch.load(run / "models.pt", weights_only=True, map_location="cpu")
        behavior = Network(states.shape[1], broad_masks.shape[1], config.hidden)
        flow = Flow(states.shape[1], broad_masks.shape[1], config.hidden)
        behavior.load_state_dict(weights["behavior"])
        flow.load_state_dict(weights["qdfm"])
        behavior.eval()
        flow.eval()
        # Keep the behavior diagnostic on the ORIGINAL support. Renormalizing it
        # into the build pool would obscure how unusual a recommended target is.
        behavior_probs.append(
            probabilities(behavior, None, states, broad_masks, config)
        )
        torch.manual_seed(seed + 947)
        broad.append(
            probabilities(behavior, flow, states, broad_masks, config, samples=1024)
        )
        probs = torch.zeros_like(broad[-1])
        if active.any():
            torch.manual_seed(seed + 947)
            # probabilities masks both the initial distribution and EVERY flow
            # step. An empty row abstains; it never falls back to hero-wide items.
            probs[active] = probabilities(
                behavior,
                flow,
                states[active],
                restricted_masks[active],
                config,
                samples=1024,
            )
        if torch.any(probs[~restricted_masks] != 0):
            raise ValueError("Policy emitted probability outside its build support")
        restricted.append(probs)
        checkpoints.append({
            "seed": seed,
            "model_sha256": checkpoint_hash,
            "config": report["config"],
        })
        print(f"Rendered frozen seed {seed}", flush=True)
    return broad, restricted, behavior_probs, checkpoints


def targets(
    predictions: list[torch.Tensor],
    behavior: torch.Tensor,
    index: int,
    actions: list[dict],
) -> list[dict]:
    average = torch.stack(predictions).mean(dim=0)[index]
    count = min(3, int((average > 0).sum()))
    return [
        {
            "action_index": action,
            "item_ids": actions[action]["item_ids"],
            "name": actions[action]["name"],
            "policy_probability": float(average[action]),
            "original_behavior_probability": float(behavior[index, action]),
            "top1_seed_votes": sum(
                bool(probs[index].sum() > 0) and int(probs[index].argmax()) == action
                for probs in predictions
            ),
        }
        for action in average.topk(count).indices.tolist()
    ]


def render(rows: list[dict], manifest: dict, output: Path) -> None:
    lines = [
        "# QDFM choices within each selected build",
        "",
        "Frozen models, restricted during generation to the selected build's core, optional items, and required components.",
        "Each path is a separate hypothetical selection at the same observed state; it is not inferred from future purchases.",
        "Historical inventory and purchase history remain intact, including items outside the selected pool.",
        "Probabilities describe model choices, not win rates. Original behavior probabilities retain the broad candidate pool.",
        "This is an inference-only preview: no retraining or new outcome evaluation. Earlier FQE estimates do not apply.",
        "Membership alone does not enforce core order, counter triggers, full-build compatibility, cash, slots, or buy-versus-wait.",
        "A basket joined by `+` is one simultaneous purchase action; every item must be in the pool.",
        "",
        "| Hero | Selected build | Items including components |",
        "| --- | --- | ---: |",
    ]
    lines += [
        f"| {pool['hero']} | {pool['path_label']} | {len(pool['items'])} |"
        for pool in manifest["pools"]
    ]
    for row in rows:
        lines += [
            "",
            f"## {row['hero']} — {row['path_label']} — {row['time_s'] // 60}:{row['time_s'] % 60:02d}",
            "",
            f"Wealth: {row['wealth']:,}; lobby percentile: {row['lobby_wealth_percentile']:.0%}; snapshot age: {row['snapshot_age_s']} seconds.",
            "",
            "Owned: " + ", ".join(row["owned_items"]) + ".",
            "",
            f"Eligible actions: {row['eligible_actions_before']} → {row['eligible_actions_after']} (includes baskets).",
        ]
        previous = row["hero_wide_targets"][0]
        lines += [
            "",
            f"Hero-wide first choice: **{previous['name']}**; "
            + (
                "outside this build pool."
                if row["hero_wide_top_excluded_by_pool"]
                else "also belongs to this pool."
            ),
        ]
        if row["abstention"]:
            lines += ["", row["abstention"]]
        else:
            lines += [
                "",
                "| Build-restricted target | QDFM choice probability | Original behavior probability | Seeds ranking it first |",
                "| --- | ---: | ---: | ---: |",
            ]
            for target in row["qdfm_targets"]:
                lines.append(
                    f"| {target['name']} | {target['policy_probability']:.1%} | "
                    f"{target['original_behavior_probability']:.4%} | {target['top1_seed_votes']}/3 |"
                )
        lines += ["", f"Recorded next purchase: {row['historical_next_purchase']}."]
    output.mkdir(parents=True, exist_ok=True)
    (output / "examples.json").write_text(json.dumps(rows, indent=2) + "\n")
    (output / "examples.md").write_text("\n".join(lines) + "\n")
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


def run(directory: Path, runs: Path, evidence: Path, output: Path) -> None:
    if output.resolve() == runs.resolve():
        raise ValueError(
            "Use a separate output directory to preserve the original previews"
        )
    torch.set_num_threads(2)
    metadata = json.loads((directory / "dataset.json").read_text())
    if (
        fingerprint(directory / "validation.npz")
        != metadata["sha256"]["validation.npz"]
    ):
        raise ValueError(
            "Validation states changed since the frozen dataset was recorded"
        )
    pools, manifest = load_pools(evidence, Path(metadata["source"]))
    fold = load_fold(str(directory / "validation.npz"))
    selections: list[tuple[int, BuildPool]] = [
        (row, pool)
        for hero_id in HEROES
        for pool in pools
        if pool.hero_id == hero_id
        for row in selected_rows(fold)
        if int(fold.hero_ids[row]) == hero_id
    ]
    indices = [row for row, _ in selections]
    states = fold.transitions.states[indices]
    broad_masks = fold.transitions.masks[indices]
    pool_masks = torch.stack([
        pool.action_mask(metadata["actions"]) for _, pool in selections
    ])
    restricted_masks = broad_masks & pool_masks
    broad, restricted, behavior, checkpoints = frozen_predictions(
        directory,
        runs,
        states,
        broad_masks,
        restricted_masks,
    )
    avg_behavior = torch.stack(behavior).mean(dim=0)
    rows = []
    for index, (row, pool) in enumerate(selections):
        unrestricted = targets(broad, avg_behavior, index, metadata["actions"])
        choices = targets(restricted, avg_behavior, index, metadata["actions"])
        rows.append({
            "hero_id": pool.hero_id,
            "hero": HEROES[pool.hero_id][0],
            "group": HEROES[pool.hero_id][1],
            "path_id": pool.path_id,
            "path_label": pool.path_label,
            "validation_row": row,
            "episode_id": int(fold.episode_ids[row]),
            "time_s": int(fold.times[row]),
            "wealth": round(float(states[index, 1]) * 50000),
            "lobby_wealth_percentile": float(states[index, 4]),
            "relative_wealth_gap": float(states[index, 3]),
            "snapshot_age_s": round(float(states[index, 10]) * 300),
            "owned_items": [
                name.removeprefix("owned:")
                for name, value in zip(metadata["features"], states[index], strict=True)
                if name.startswith("owned:") and value > 0
            ],
            "pool_item_count": len(pool.item_ids),
            "eligible_actions_before": int(broad_masks[index].sum()),
            "eligible_actions_after": int(restricted_masks[index].sum()),
            "hero_wide_targets": unrestricted,
            "hero_wide_top_excluded_by_pool": not bool(
                pool_masks[index, unrestricted[0]["action_index"]]
            ),
            "qdfm_targets": choices,
            "abstention": None
            if choices
            else "No supported, inventory-legal action remains in this build pool.",
            "historical_next_purchase": metadata["actions"][
                int(fold.transitions.actions[row])
            ]["name"],
            "label": "Frozen hero-wide model with a selected-build candidate mask; purchase quality remains unevaluated.",
        })
    manifest.update({
        "mode": "inference_only_build_pool_restriction",
        "promotion": False,
        "dataset_sha256": fingerprint(directory / "dataset.json"),
        "validation_sha256": metadata["sha256"]["validation.npz"],
        "checkpoints": checkpoints,
        "flow_samples_per_state_seed": 1024,
        "sampling_seed_rule": "training seed + 947, separately for broad/restricted sampling",
        "history_modified": False,
        "retrained": False,
        "outcome_evaluation": "not run",
        "tests_run": False,
        "steam_accessed": False,
        "selection": "three observed validation states near 15 minutes per hero, repeated for every selected build",
        "build_selection_evidence": "existing frozen generator artifact, not a training-only pool for new held-out outcome evaluation",
        "preview_rows": len(rows),
        "abstentions": sum(row["abstention"] is not None for row in rows),
        "broad_top_excluded_rows": sum(
            row["hero_wide_top_excluded_by_pool"] for row in rows
        ),
    })
    render(rows, manifest, output)
    print(
        json.dumps({
            key: manifest[key]
            for key in ("preview_rows", "abstentions", "broad_top_excluded_rows")
        })
    )
    print(output / "examples.md")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--runs", required=True, type=Path)
    parser.add_argument("--build-evidence", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    run(args.directory, args.runs, args.build_evidence, args.output)
