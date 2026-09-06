"""Categorical IQL, CQL, and QQL research adaptations; see ALGORITHMS.md."""

from __future__ import annotations

import copy
import math
import time
from dataclasses import dataclass
from itertools import chain

import torch
from torch import Tensor, nn
from torch.nn import functional

from tools.comparisons.qdfm.model import Network, Transitions, masked_probs, update

EULER = 0.5772156649015329
QQL_SOFT = 1 - math.exp(-1)
QQL_HIGH = 1 - math.exp(-math.exp(EULER))
QQL_LOW = 1 - math.exp(-math.exp(-EULER))
METHODS = ("bc", "iql", "cql", "qql")


@dataclass(frozen=True)
class AlgorithmConfig:
    method: str
    seed: int = 42
    steps: int = 6000
    hidden: int = 128
    batch: int = 128
    learning_rate: float = 0.0003
    gamma: float = 1.0
    target_tau: float = 0.005
    expectile: float = 0.7
    iql_inverse_temperature: float = 5.0
    cql_alpha: float = 0.1
    qql_temperature_floor: float = 0.1
    qql_zeta: float = 1.0
    qql_mild: float = 1.0


def asymmetric_loss(residual: Tensor, level: float, *, squared: bool) -> Tensor:
    weight = torch.where(residual >= 0, level, 1 - level)
    error = residual.square() if squared else residual.abs()
    return (weight * error).mean()


def selected(values: Tensor, actions: Tensor) -> Tensor:
    return values.gather(1, actions[:, None]).squeeze(1)


def conservative_penalty(values: Tensor, actions: Tensor, masks: Tensor) -> Tensor:
    if not bool(masks.gather(1, actions[:, None]).all()):
        raise ValueError("Recorded action is outside legal support")
    partition = values.masked_fill(~masks, -torch.inf).logsumexp(dim=1)
    return (partition - selected(values, actions)).mean()


def qql_target(
    batch: Transitions, following: Tensor, gap: Tensor, gamma: float
) -> Tensor:
    # The CURRENT gap is subtracted even on terminal transitions (paper Eq. 5).
    return batch.rewards + gamma * (~batch.done).float() * following - gap


def advantage_weights(log_weights: Tensor) -> Tensor:
    # Clamp before exponentiation so a large finite input cannot overflow.
    return log_weights.clamp(max=math.log(100)).exp()


class Learner(nn.Module):
    def __init__(self, inputs: int, actions: int, config: AlgorithmConfig) -> None:
        super().__init__()
        if config.method not in METHODS or config.steps < 1:
            raise ValueError("Unknown algorithm or empty training budget")
        self.config = config
        self.actor = Network(inputs, actions, config.hidden)
        self.q1 = Network(inputs, actions, config.hidden)
        self.q2 = Network(inputs, actions, config.hidden)
        self.target1 = copy.deepcopy(self.q1).requires_grad_(requires_grad=False)
        self.target2 = copy.deepcopy(self.q2).requires_grad_(requires_grad=False)
        self.value = Network(inputs, 1, config.hidden)
        self.soft_value = Network(inputs, 1, config.hidden)

    def minimum(self, states: Tensor, *, target: bool = False) -> Tensor:
        first, second = (self.target1, self.target2) if target else (self.q1, self.q2)
        return torch.minimum(first(states), second(states))

    @torch.no_grad()
    def policy(self, states: Tensor, masks: Tensor) -> Tensor:
        active = masks.any(dim=1)
        result = torch.zeros_like(masks, dtype=torch.float32)
        if not active.any():
            return result
        if self.config.method == "cql":
            values = self.minimum(states[active]).masked_fill(
                ~masks[active], -torch.inf
            )
            result[active] = functional.one_hot(
                values.argmax(dim=1), masks.shape[1]
            ).float()
        else:
            result[active] = masked_probs(self.actor(states[active]), masks[active])
        return result

    @torch.no_grad()
    def polyak(self) -> None:
        for old, new in zip(
            chain(self.target1.parameters(), self.target2.parameters()),
            chain(self.q1.parameters(), self.q2.parameters()),
            strict=True,
        ):
            old.lerp_(new, self.config.target_tau)


class Trainer:
    def __init__(self, model: Learner) -> None:
        self.model = model
        self.config = model.config
        groups = {
            "actor": model.actor.parameters(),
            "q": chain(model.q1.parameters(), model.q2.parameters()),
            "v": model.value.parameters(),
            "soft": model.soft_value.parameters(),
        }
        self.optimizers = {
            name: torch.optim.Adam(parameters, lr=self.config.learning_rate)
            for name, parameters in groups.items()
        }
        self.schedule = torch.optim.lr_scheduler.CosineAnnealingLR(
            self.optimizers["actor"], T_max=self.config.steps
        )

    def actor_step(self, batch: Transitions, weights: Tensor) -> float:
        logits = self.model.actor(batch.states).masked_fill(~batch.masks, -torch.inf)
        loss = (
            functional.cross_entropy(logits, batch.actions, reduction="none") * weights
        ).mean()
        update(self.optimizers["actor"], loss)
        self.schedule.step()
        return float(loss.detach())

    def critic_step(
        self, batch: Transitions, targets: Tensor, *, conservative: bool = False
    ) -> float:
        losses = []
        for network in (self.model.q1, self.model.q2):
            values = network(batch.states)
            loss = functional.mse_loss(selected(values, batch.actions), targets)
            if conservative:
                loss += self.config.cql_alpha * conservative_penalty(
                    values, batch.actions, batch.masks
                )
            losses.append(loss)
        loss = torch.stack(losses).mean()
        update(self.optimizers["q"], loss)
        self.model.polyak()
        return float(loss.detach())

    def cql_step(self, batch: Transitions) -> dict:
        with torch.no_grad():
            following_actions = (
                self.model
                .minimum(batch.next_states)
                .masked_fill(~batch.next_masks, -torch.inf)
                .argmax(dim=1)
            )
            following = selected(
                self.model.minimum(batch.next_states, target=True), following_actions
            )
            targets = (
                batch.rewards + self.config.gamma * (~batch.done).float() * following
            )
        return {"critic": self.critic_step(batch, targets, conservative=True)}

    def iql_step(self, batch: Transitions) -> dict:
        with torch.no_grad():
            q = selected(self.model.minimum(batch.states, target=True), batch.actions)
        residual = q - self.model.value(batch.states).squeeze(1)
        loss = asymmetric_loss(residual, self.config.expectile, squared=True)
        update(self.optimizers["v"], loss)
        with torch.no_grad():
            advantage = q - self.model.value(batch.states).squeeze(1)
            weights = advantage_weights(self.config.iql_inverse_temperature * advantage)
            following = self.model.value(batch.next_states).squeeze(1)
            targets = (
                batch.rewards + self.config.gamma * (~batch.done).float() * following
            )
        actor_loss = self.actor_step(batch, weights)
        return {
            "value": float(loss.detach()),
            "actor": actor_loss,
            "critic": self.critic_step(batch, targets),
        }

    def quantile_step(
        self, states: Tensor, q: Tensor, level: float, scale: float = 1, *, soft: bool
    ) -> Tensor:
        network = self.model.soft_value if soft else self.model.value
        residual = q - network(states).squeeze(1)
        loss = scale * asymmetric_loss(residual, level, squared=False)
        update(self.optimizers["soft" if soft else "v"], loss)
        return residual.detach()

    def imagination_step(self, batch: Transitions) -> None:
        # Terminal next_states are placeholders, not observed decision states.
        active = ~batch.done
        if not active.any():
            return
        states, masks = batch.next_states[active], batch.next_masks[active]
        for soft, level in ((False, QQL_SOFT), (True, QQL_LOW)):
            with torch.no_grad():
                actions = torch.multinomial(
                    self.model.policy(states, masks), 1
                ).squeeze(1)
                q = selected(self.model.minimum(states, target=True), actions)
            self.quantile_step(states, q, level, self.config.qql_mild, soft=soft)

    def qql_step(self, batch: Transitions) -> dict:
        with torch.no_grad():
            following = self.model.value(batch.next_states).squeeze(1)
            q = selected(self.model.minimum(batch.states, target=True), batch.actions)
        soft_advantage = self.quantile_step(batch.states, q, QQL_SOFT, soft=True)
        advantage = self.quantile_step(batch.states, q, QQL_HIGH, soft=False)
        with torch.no_grad():
            gap = (
                self.model.value(batch.states) - self.model.soft_value(batch.states)
            ).squeeze(1)
            targets = qql_target(batch, following, gap, self.config.gamma)
            temperature = self.config.qql_temperature_floor + gap.abs() / EULER
            weights = advantage_weights(
                (advantage / self.config.qql_zeta + soft_advantage) / temperature
            )
        critic_loss = self.critic_step(batch, targets)
        actor_loss = self.actor_step(batch, weights)
        self.imagination_step(batch)
        return {
            "critic": critic_loss,
            "actor": actor_loss,
            "mean_gap": float(gap.mean()),
            "mean_temperature": float(temperature.mean()),
        }

    def step(self, batch: Transitions) -> dict:
        if not bool(batch.masks.gather(1, batch.actions[:, None]).all()):
            raise ValueError("Recorded purchase was masked during training")
        if not bool(batch.next_masks.any(dim=1).all()):
            raise ValueError("Missing next-state support")
        if self.config.method == "bc":
            return {"actor": self.actor_step(batch, torch.ones_like(batch.rewards))}
        methods = {"iql": self.iql_step, "cql": self.cql_step, "qql": self.qql_step}
        return methods[self.config.method](batch)


def fit(data: Transitions, config: AlgorithmConfig) -> tuple[Learner, list[dict]]:
    torch.manual_seed(config.seed)
    model = Learner(data.states.shape[1], data.masks.shape[1], config)
    trainer = Trainer(model)
    started = time.monotonic()
    history = []
    for step in range(config.steps):
        metrics = trainer.step(data.batch(config.batch))
        if (step + 1) % 500 == 0 or step == config.steps - 1:
            row = {"step": step + 1, "elapsed_s": time.monotonic() - started, **metrics}
            history.append(row)
            print(f"{config.method} seed={config.seed} {row}", flush=True)
    return model.eval(), history
