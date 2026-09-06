"""Single-objective QDFM reproduction of arXiv:2602.06138v2, Appendix E.

The policy is a time-dependent CTMC generator, not a static classifier.
Documented adaptations: bounded endpoint parameterization, finite time grid,
legal/support masks, terminal handling, and a Polyak target critic.
"""

from __future__ import annotations

import copy
import time
from dataclasses import dataclass

import torch
from torch import Tensor, nn
from torch.nn import functional


@dataclass(frozen=True)
class Config:
    hidden: int = 128
    batch: int = 128
    learning_rate: float = 0.0003
    behavior_steps: int = 1500
    warmup_steps: int = 1500
    critic_steps: int = 3000
    improve_steps: int = 1000
    support_size: int = 16
    flow_steps: int = 20
    beta: float = 5.0
    gamma: float = 1.0
    target_tau: float = 0.01
    seed: int = 42


@dataclass
class Transitions:
    states: Tensor
    actions: Tensor
    rewards: Tensor
    next_states: Tensor
    done: Tensor
    masks: Tensor
    next_masks: Tensor

    def batch(self, size: int) -> Transitions:
        indices = torch.randint(len(self.actions), (size,))
        return Transitions(
            *(
                value[indices]
                for value in (
                    self.states,
                    self.actions,
                    self.rewards,
                    self.next_states,
                    self.done,
                    self.masks,
                    self.next_masks,
                )
            )
        )


class Network(nn.Module):
    def __init__(self, inputs: int, outputs: int, hidden: int) -> None:
        super().__init__()
        self.layers = nn.Sequential(
            nn.Linear(inputs, hidden),
            nn.ReLU(),
            nn.Linear(hidden, hidden),
            nn.ReLU(),
            nn.Linear(hidden, outputs),
        )

    def forward(self, states: Tensor) -> Tensor:
        return self.layers(states)


def masked_probs(logits: Tensor, mask: Tensor) -> Tensor:
    if not bool(mask.any(dim=-1).all()):
        raise ValueError("Empty candidate support: policy must abstain")
    return logits.masked_fill(~mask, -torch.inf).softmax(dim=-1)


class Flow(nn.Module):
    def __init__(self, inputs: int, actions: int, hidden: int) -> None:
        super().__init__()
        self.actions = actions
        self.network = Network(inputs + actions + 1, actions, hidden)

    def rates(
        self, states: Tensor, current: Tensor, times: Tensor, masks: Tensor
    ) -> Tensor:
        encoded = functional.one_hot(current, self.actions).float()
        inputs = torch.cat((states, encoded, times[:, None]), dim=1)
        endpoint = masked_probs(self.network(inputs), masks)
        rates = endpoint / (1 - times[:, None])
        return rates.scatter(1, current[:, None], 0)

    def generator(
        self, states: Tensor, current: Tensor, times: Tensor, masks: Tensor
    ) -> Tensor:
        rates = self.rates(states, current, times, masks)
        return rates.scatter(1, current[:, None], -rates.sum(dim=-1, keepdim=True))

    @torch.no_grad()
    def sample(
        self,
        states: Tensor,
        initial: Tensor,
        masks: Tensor,
        steps: int,
        samples: int = 1,
    ) -> Tensor:
        states = states.repeat_interleave(samples, dim=0)
        masks = masks.repeat_interleave(samples, dim=0)
        current = torch.multinomial(initial, samples, replacement=True).flatten()
        for step in range(steps):
            times = torch.full((len(current),), step / steps)
            rates = self.rates(states, current, times, masks)
            probabilities = rates / steps
            stay = (1 - probabilities.sum(dim=1, keepdim=True)).clamp_min(0)
            probabilities = probabilities.scatter(1, current[:, None], stay)
            current = torch.multinomial(probabilities, 1).squeeze(1)
        return current.reshape(-1, samples)


def conditional_generator(
    current: Tensor, endpoint: Tensor, times: Tensor, actions: int
) -> Tensor:
    target = functional.one_hot(endpoint, actions).float()
    target = target * (current != endpoint)[:, None] / (1 - times[:, None])
    return target.scatter(1, current[:, None], -target.sum(dim=-1, keepdim=True))


def flow_loss(
    flow: Flow,
    states: Tensor,
    start: Tensor,
    endpoint: Tensor,
    masks: Tensor,
    steps: int,
) -> Tensor:
    times = torch.randint(steps, (len(start),)).float() / steps
    current = torch.where(torch.rand(len(start)) < times, endpoint, start)
    target = conditional_generator(current, endpoint, times, flow.actions)
    actual = flow.generator(states, current, times, masks)
    return (target - actual).square().sum(dim=-1)


def critic_target(
    rewards: Tensor, done: Tensor, next_values: Tensor, gamma: float
) -> Tensor:
    return rewards + gamma * (~done).float() * next_values


def update(optimizer: torch.optim.Optimizer, loss: Tensor) -> None:
    if not bool(torch.isfinite(loss)):
        raise ValueError("Nonfinite training loss")
    optimizer.zero_grad()
    loss.backward()
    optimizer.step()


def progress(stage: str, step: int, loss: Tensor, started: float) -> None:
    if step % 500 == 0:
        print(
            f"{stage} step={step} loss={loss.item():.5f} "
            f"elapsed={time.monotonic() - started:.1f}s",
            flush=True,
        )


def train_behavior(data: Transitions, config: Config) -> Network:
    model = Network(data.states.shape[1], data.masks.shape[1], config.hidden)
    optimizer = torch.optim.Adam(model.parameters(), lr=config.learning_rate)
    started = time.monotonic()
    for step in range(config.behavior_steps):
        batch = data.batch(config.batch)
        logits = model(batch.states).masked_fill(~batch.masks, -torch.inf)
        loss = functional.cross_entropy(logits, batch.actions)
        update(optimizer, loss)
        progress("behavior", step, loss, started)
    return model.eval()


def warmup(data: Transitions, behavior: Network, config: Config) -> Flow:
    flow = Flow(data.states.shape[1], data.masks.shape[1], config.hidden)
    optimizer = torch.optim.Adam(flow.parameters(), lr=config.learning_rate)
    started = time.monotonic()
    for step in range(config.warmup_steps):
        batch = data.batch(config.batch)
        with torch.no_grad():
            probs = masked_probs(behavior(batch.states), batch.masks)
            endpoints = torch.multinomial(probs, 1).squeeze(1)
            starts = torch.multinomial(batch.masks.float(), 1).squeeze(1)
        loss = flow_loss(
            flow, batch.states, starts, endpoints, batch.masks, config.flow_steps
        ).mean()
        update(optimizer, loss)
        progress("flow-warmup", step, loss, started)
    return flow.eval()


def train_critic(data: Transitions, behavior: Network, config: Config) -> Network:
    critic = Network(data.states.shape[1], data.masks.shape[1], config.hidden)
    target = copy.deepcopy(critic).eval()
    optimizer = torch.optim.Adam(critic.parameters(), lr=config.learning_rate)
    started = time.monotonic()
    for step in range(config.critic_steps):
        batch = data.batch(config.batch)
        with torch.no_grad():
            probs = masked_probs(behavior(batch.next_states), batch.next_masks)
            candidates = torch.multinomial(probs, config.support_size, replacement=True)
            values = target(batch.next_states).sigmoid().gather(1, candidates)
            weights = (config.beta * values).softmax(dim=1)
            expected = (values * weights).sum(dim=1)
            targets = critic_target(batch.rewards, batch.done, expected, config.gamma)
        values = (
            critic(batch.states).sigmoid().gather(1, batch.actions[:, None]).squeeze(1)
        )
        loss = functional.mse_loss(values, targets)
        update(optimizer, loss)
        with torch.no_grad():
            for old, new in zip(target.parameters(), critic.parameters(), strict=True):
                old.lerp_(new, config.target_tau)
        progress("critic", step, loss, started)
    return critic.eval()


def improve(
    data: Transitions, behavior: Network, critic: Network, flow: Flow, config: Config
) -> Flow:
    optimizer = torch.optim.Adam(flow.parameters(), lr=config.learning_rate)
    started = time.monotonic()
    for step in range(config.improve_steps):
        batch = data.batch(config.batch)
        with torch.no_grad():
            initial = masked_probs(behavior(batch.states), batch.masks)
            endpoints = flow.sample(
                batch.states,
                initial,
                batch.masks,
                config.flow_steps,
                config.support_size,
            )
            values = critic(batch.states).sigmoid().gather(1, endpoints)
            weights = (config.beta * values).softmax(dim=1)
        count = config.support_size
        losses = flow_loss(
            flow,
            batch.states.repeat_interleave(count, dim=0),
            batch.actions.repeat_interleave(count),
            endpoints.flatten(),
            batch.masks.repeat_interleave(count, dim=0),
            config.flow_steps,
        )
        loss = (weights * losses.reshape(-1, count)).sum(dim=1).mean()
        update(optimizer, loss)
        progress("policy-improvement", step, loss, started)
    return flow.eval()


def train(data: Transitions, config: Config) -> tuple[Network, Network, Flow, Flow]:
    torch.manual_seed(config.seed)
    behavior = train_behavior(data, config)
    flow = warmup(data, behavior, config)
    critic = train_critic(data, behavior, config)
    unweighted = copy.deepcopy(flow)
    flow = improve(data, behavior, critic, flow, config)
    return behavior, critic, unweighted, flow
