"""Known-outcome two-purchase task; checks context and continuation learning."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

import numpy as np
import torch

from experiments.qdfm.model import (
    Config,
    Flow,
    Network,
    Transitions,
    masked_probs,
    train,
)


def success(wealth: int, threat: int, first: int, second: int) -> float:
    if second != first + 2:
        return 0.1
    values = {
        (0, 0): (0.65, 0.60),
        (0, 1): (0.85, 0.30),
        (1, 0): (0.55, 0.90),
        (1, 1): (0.80, 0.65),
    }
    return values[wealth, threat][first]


def make_data(seed: int, episodes: int = 12000) -> Transitions:
    rng = np.random.default_rng(seed)
    states, actions, rewards, next_states, done, masks, next_masks = (
        [] for _ in range(7)
    )
    for _ in range(episodes):
        wealth, threat = (int(value) for value in rng.integers(0, 2, size=2))
        first = int(rng.random() < 0.65)
        second = int(rng.integers(2, 4))
        state = [wealth, threat, 0, 0, 0]
        following = [wealth, threat, 1, int(first == 0), int(first == 1)]
        reward = int(rng.random() < success(wealth, threat, first, second))
        states.extend([state, following])
        actions.extend([first, second])
        rewards.extend([0, reward])
        next_states.extend([following, [0] * 5])
        done.extend([False, True])
        masks.extend([[True, True, False, False], [False, False, True, True]])
        next_masks.extend([[False, False, True, True], [True, False, False, False]])
    return Transitions(
        torch.tensor(states).float(),
        torch.tensor(actions),
        torch.tensor(rewards).float(),
        torch.tensor(next_states).float(),
        torch.tensor(done),
        torch.tensor(masks),
        torch.tensor(next_masks),
    )


@torch.no_grad()
def distribution(
    behavior: Network,
    flow: Flow | None,
    state: list[int],
    mask: list[bool],
    config: Config,
) -> np.ndarray:
    states = torch.tensor([state]).float()
    masks = torch.tensor([mask])
    initial = masked_probs(behavior(states), masks)
    if flow is None:
        return initial[0].numpy()
    draws = flow.sample(states, initial, masks, config.flow_steps, 4000)
    return torch.bincount(draws.flatten(), minlength=4).numpy() / 4000


def evaluate(behavior: Network, flow: Flow | None, config: Config) -> dict[str, object]:
    rows = []
    for wealth in (0, 1):
        for threat in (0, 1):
            first_probs = distribution(
                behavior,
                flow,
                [wealth, threat, 0, 0, 0],
                [True, True, False, False],
                config,
            )
            expected = 0.0
            continuation = []
            for first in (0, 1):
                state = [wealth, threat, 1, int(first == 0), int(first == 1)]
                follow = distribution(
                    behavior, flow, state, [False, False, True, True], config
                )
                continuation.append(float(follow[first + 2]))
                expected += sum(
                    first_probs[first]
                    * follow[second]
                    * success(wealth, threat, first, second)
                    for second in (2, 3)
                )
            rows.append({
                "ahead": bool(wealth),
                "heavy_threat": bool(threat),
                "defense_probability": float(first_probs[0]),
                "compatible_continuation_probability": continuation,
                "true_expected_success": float(expected),
            })
    return {
        "mean_true_expected_success": float(
            np.mean([row["true_expected_success"] for row in rows])
        ),
        "contexts": rows,
    }


def run(output: Path, seed: int) -> None:
    torch.set_num_threads(2)
    config = Config(
        hidden=64,
        behavior_steps=1000,
        warmup_steps=1500,
        critic_steps=2500,
        improve_steps=1200,
        seed=seed,
    )
    data = make_data(seed)
    behavior, critic, unweighted, flow = train(data, config)
    result = {
        "config": asdict(config),
        "environment": "synthetic two-purchase task",
        "optimal_success": 0.8,
        "behavior": evaluate(behavior, None, config),
        "unweighted_flow": evaluate(behavior, unweighted, config),
        "qdfm": evaluate(behavior, flow, config),
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / f"toy-seed-{seed}.json").write_text(json.dumps(result, indent=2) + "\n")
    torch.save(
        {
            "behavior": behavior.state_dict(),
            "critic": critic.state_dict(),
            "unweighted_flow": unweighted.state_dict(),
            "flow": flow.state_dict(),
        },
        output / f"toy-seed-{seed}.pt",
    )
    print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--seed", type=int, default=42)
    arguments = parser.parse_args()
    run(arguments.output, arguments.seed)
