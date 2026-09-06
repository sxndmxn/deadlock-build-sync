"""Frozen-policy evaluation diagnostics; estimates do not establish causal gain."""

from __future__ import annotations

import copy
from dataclasses import dataclass

import numpy as np
import torch
from torch import Tensor
from torch.nn import functional

from tools.comparisons.qdfm.model import (
    Config,
    Flow,
    Network,
    Transitions,
    critic_target,
    masked_probs,
    update,
)


@dataclass
class Fold:
    transitions: Transitions
    episode_ids: np.ndarray
    hero_ids: np.ndarray
    times: np.ndarray
    step_indices: np.ndarray


def load_fold(path: str) -> Fold:
    with np.load(path, allow_pickle=False) as arrays:
        data = Transitions(
            torch.from_numpy(arrays["states"]).float(),
            torch.from_numpy(arrays["actions"]).long(),
            torch.from_numpy(arrays["rewards"]).float(),
            torch.from_numpy(arrays["next_states"]).float(),
            torch.from_numpy(arrays["done"]).bool(),
            torch.from_numpy(arrays["masks"]).bool(),
            torch.from_numpy(arrays["next_masks"]).bool(),
        )
        return Fold(
            data,
            arrays["episode_ids"],
            arrays["hero_ids"],
            arrays["times"],
            arrays["step_indices"],
        )


@torch.no_grad()
def probabilities(
    behavior: Network,
    flow: Flow | None,
    states: Tensor,
    masks: Tensor,
    config: Config,
    samples: int = 64,
) -> Tensor:
    chunks = []
    for offset in range(0, len(states), 256):
        state, mask = states[offset : offset + 256], masks[offset : offset + 256]
        initial = masked_probs(behavior(state), mask)
        if flow is None:
            chunks.append(initial)
        else:
            draws = flow.sample(state, initial, mask, config.flow_steps, samples)
            counts = torch.zeros_like(initial)
            counts.scatter_add_(1, draws, torch.ones_like(draws).float())
            chunks.append(counts / samples)
    return torch.cat(chunks)


def fitted_evaluation(
    data: Transitions, next_probs: Tensor, config: Config, steps: int = 4000
) -> Network:
    model = Network(data.states.shape[1], data.masks.shape[1], config.hidden)
    target = copy.deepcopy(model).eval()
    optimizer = torch.optim.Adam(model.parameters(), lr=config.learning_rate)
    for _ in range(steps):
        indices = torch.randint(len(data.actions), (config.batch,))
        with torch.no_grad():
            next_value = (
                next_probs[indices] * target(data.next_states[indices]).sigmoid()
            ).sum(dim=1)
            expected = critic_target(
                data.rewards[indices], data.done[indices], next_value, config.gamma
            )
        predicted = (
            model(data.states[indices])
            .sigmoid()
            .gather(1, data.actions[indices, None])
            .squeeze(1)
        )
        update(optimizer, functional.mse_loss(predicted, expected))
        with torch.no_grad():
            for old, new in zip(target.parameters(), model.parameters(), strict=True):
                old.lerp_(new, config.target_tau)
    return model.eval()


@torch.no_grad()
def initial_values(
    model: Network, behavior: Network, flow: Flow | None, fold: Fold, config: Config
) -> tuple[np.ndarray, np.ndarray]:
    initial = np.flatnonzero(fold.step_indices == 0)
    states = fold.transitions.states[initial]
    masks = fold.transitions.masks[initial]
    probs = probabilities(behavior, flow, states, masks, config, samples=256)
    values = (probs * model(states).sigmoid()).sum(dim=1).numpy()
    return initial, values


@torch.no_grad()
def behavior_diagnostics(model: Network, fold: Fold) -> dict[str, float]:
    data = fold.transitions
    probs = probabilities(model, None, data.states, data.masks, Config())
    observed = probs.gather(1, data.actions[:, None]).squeeze(1)
    return {
        "next_action_nll": float(-observed.clamp_min(1e-12).log().mean()),
        "top1": float((probs.argmax(dim=1) == data.actions).float().mean()),
        "top5": float(
            (probs.topk(5, dim=1).indices == data.actions[:, None])
            .any(dim=1)
            .float()
            .mean()
        ),
        "mean_observed_action_probability": float(observed.mean()),
    }


def bootstrap_mean(values: np.ndarray, seed: int = 731) -> list[float]:
    rng = np.random.default_rng(seed)
    samples = np.array([
        rng.choice(values, len(values), replace=True).mean() for _ in range(1000)
    ])
    return [float(value) for value in np.quantile(samples, [0.025, 0.975])]


def hero_results(
    fold: Fold,
    initial: np.ndarray,
    behavior_values: np.ndarray,
    flow_values: np.ndarray,
    episodes: list[dict[str, object]],
) -> list[dict[str, object]]:
    results = []
    for hero in sorted(set(fold.hero_ids)):
        selected = fold.hero_ids[initial] == hero
        identities = fold.episode_ids[initial[selected]]
        outcomes = np.array(
            [episodes[int(identity)]["won"] for identity in identities], dtype=float
        )
        differences = flow_values[selected] - behavior_values[selected]
        baseline_error = float(behavior_values[selected].mean() - outcomes.mean())
        results.append({
            "hero_id": int(hero),
            "episodes": int(selected.sum()),
            "observed_win_rate": float(outcomes.mean()),
            "behavior_fqe": float(behavior_values[selected].mean()),
            "qdfm_fqe": float(flow_values[selected].mean()),
            "paired_fqe_difference": float(differences.mean()),
            "sampling_only_95pct_interval": bootstrap_mean(differences),
            "behavior_fqe_calibration_error": baseline_error,
            "interpretation": "Model-based estimate; interval excludes model and confounding uncertainty.",
            "promotion": False,
        })
    return results
