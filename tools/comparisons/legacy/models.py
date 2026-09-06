from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from operator import itemgetter

import numpy as np
from scipy.optimize import minimize
from scipy.special import betaln
from scipy.stats import beta


@dataclass(frozen=True)
class BetaPrior:
    alpha: float
    beta: float
    source: str

    @property
    def mean(self) -> float:
        return self.alpha / (self.alpha + self.beta)

    @property
    def strength(self) -> float:
        return self.alpha + self.beta


def prior_snapshot_value(
    timestamps: Iterable[int], values: Iterable[int], decision_time: int
) -> int | None:
    eligible = [
        (timestamp, value)
        for timestamp, value in zip(timestamps, values, strict=True)
        if timestamp <= decision_time
    ]
    return max(eligible, default=(0, None), key=itemgetter(0))[1]


def phase_for_time(game_time_s: int) -> int:
    if game_time_s < 540:
        return 0
    if game_time_s < 1200:
        return 1
    if game_time_s < 1800:
        return 2
    return 3


def wilson_interval(
    wins: int, observations: int, z: float = 1.96
) -> tuple[float, float]:
    if observations <= 0:
        return 0.0, 0.0
    p = wins / observations
    z2 = z * z
    denominator = 1 + z2 / observations
    center = p + z2 / (2 * observations)
    margin = z * math.sqrt((p * (1 - p) + z2 / (4 * observations)) / observations)
    return (center - margin) / denominator, (center + margin) / denominator


def fit_beta_prior(
    cells: Iterable[tuple[int, int]],
    *,
    fallback_mean: float = 0.5,
    fallback_strength: float = 50.0,
    source: str = "fitted",
) -> BetaPrior:
    values = [(int(wins), int(n)) for wins, n in cells if n > 0 and 0 <= wins <= n]
    if len(values) < 4:
        return BetaPrior(
            max(0.01, fallback_mean * fallback_strength),
            max(0.01, (1 - fallback_mean) * fallback_strength),
            "pooled-fallback",
        )
    wins = np.asarray([row[0] for row in values], dtype=float)
    observations = np.asarray([row[1] for row in values], dtype=float)
    pooled = float(wins.sum() / observations.sum())

    def objective(log_parameters: np.ndarray) -> float:
        alpha, beta_value = np.exp(log_parameters)
        likelihood = (
            betaln(wins + alpha, observations - wins + beta_value)
            - betaln(alpha, beta_value)
        ).sum()
        return -float(likelihood)

    initial_strength = 50.0
    initial = np.log([
        max(0.01, pooled * initial_strength),
        max(0.01, (1 - pooled) * initial_strength),
    ])
    result = minimize(
        objective,
        initial,
        method="L-BFGS-B",
        bounds=((math.log(0.01), math.log(500.0)),) * 2,
    )
    if not result.success or not np.all(np.isfinite(result.x)):
        return BetaPrior(
            max(0.01, pooled * fallback_strength),
            max(0.01, (1 - pooled) * fallback_strength),
            "optimization-fallback",
        )
    alpha, beta_value = np.exp(result.x)
    strength = min(500.0, max(5.0, float(alpha + beta_value)))
    return BetaPrior(
        max(0.01, pooled * strength),
        max(0.01, (1 - pooled) * strength),
        source,
    )


def beta_posterior(
    wins: int,
    observations: int,
    prior: BetaPrior,
    credibility: float = 0.95,
) -> tuple[float, float, float]:
    alpha = prior.alpha + wins
    beta_value = prior.beta + observations - wins
    mean = alpha / (alpha + beta_value)
    tail = (1 - credibility) / 2
    return (
        mean,
        float(beta.ppf(tail, alpha, beta_value)),
        float(beta.ppf(1 - tail, alpha, beta_value)),
    )
