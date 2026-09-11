"""Estimate the common state-dependent item score from training counts."""

from __future__ import annotations

import json
import math
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from pathlib import Path

    from .records import Query, ScoringConfig, SearchState


class ItemModel:
    def __init__(self, statistics: dict[str, object], config: ScoringConfig) -> None:
        if statistics["partition"] != "train":
            raise ValueError("The item model accepts training statistics only")
        self.patch = str(statistics["patch"])
        self.fingerprint = str(statistics["fingerprint"])
        self.config = config
        self.candidate_cache: dict[tuple[int, int, int, int], tuple[int, ...]] = {}
        self.heroes = tuple(int(row[0]) for row in statistics["hero_counts"])
        self.hero_index = {hero: index for index, hero in enumerate(self.heroes)}
        self.item_ids = tuple(int(item) for item in statistics["item_ids"])
        item_index = {item: index for index, item in enumerate(self.item_ids)}
        shape = len(self.heroes), 12, 3, len(self.item_ids)
        self.counts = np.zeros(shape, dtype=np.float64)
        self.wins = np.zeros(shape, dtype=np.float64)
        state_counts = np.zeros(shape[:-1], dtype=np.float64)
        state_wins = np.zeros(shape[:-1], dtype=np.float64)
        hero_priors = np.asarray([
            (row[2] + 1) / (row[1] + 2) for row in statistics["hero_counts"]
        ])
        self.hero_priors = hero_priors
        for hero, wealth, relative, item, count, wins in statistics["item_counts"]:
            if int(item) in item_index:
                key = (
                    self.hero_index[int(hero)],
                    int(wealth),
                    int(relative),
                    item_index[int(item)],
                )
                self.counts[key], self.wins[key] = count, wins
        for hero, wealth, relative, count, wins in statistics["state_counts"]:
            key = self.hero_index[int(hero)], int(wealth), int(relative)
            state_counts[key], state_wins[key] = count, wins
        if not config.state_aware:
            self.counts[:] = self.counts.sum(axis=(1, 2), keepdims=True)
            self.wins[:] = self.wins.sum(axis=(1, 2), keepdims=True)
            self.baselines = np.broadcast_to(
                hero_priors[:, None, None], shape[:-1]
            ).copy()
        else:
            self.baselines = (state_wins + 20 * hero_priors[:, None, None]) / (
                state_counts + 20
            )
        alpha = self.wins + config.prior_strength * self.baselines[..., None]
        beta = (
            self.counts
            - self.wins
            + config.prior_strength * (1 - self.baselines[..., None])
        )
        total = alpha + beta
        self.means = alpha / total
        self.variances = alpha * beta / (total * total * (total + 1))
        self.utilities = (
            self.means
            - self.baselines[..., None]
            - config.uncertainty_multiplier * np.sqrt(self.variances)
        )

    @classmethod
    def load(cls, path: Path, config: ScoringConfig) -> ItemModel:
        return cls(json.loads(path.read_text(encoding="utf-8")), config)

    def cell(
        self, hero: int, net_worth: int, relative_state: int, item: int
    ) -> tuple[float, int, float]:
        key = self.hero_index[hero], min(11, net_worth // 4000), relative_state, item
        return float(self.utilities[key]), int(self.counts[key]), float(self.means[key])

    def action_utility(
        self,
        query: Query,
        net_worth: int,
        item: int,
        cash_cost: int,
        depth: int,
    ) -> tuple[float, int]:
        utility, count, _ = self.cell(query.hero, net_worth, query.relative_state, item)
        cost_scale = max(cash_cost, 800) / 1600
        value = (
            utility
            * self.config.discount**depth
            / cost_scale**self.config.cost_exponent
        )
        return value, count

    def candidate_items(self, query: Query, state: SearchState) -> tuple[int, ...]:
        first = min(11, state.net_worth // 4000)
        maximum_income = max(0, query.budget - state.spent - state.cash)
        last = min(11, (state.net_worth + maximum_income) // 4000)
        key = query.hero, query.relative_state, first, last
        if key not in self.candidate_cache:
            if len(self.candidate_cache) >= 4096:
                self.candidate_cache.clear()
            counts = self.counts[
                self.hero_index[query.hero], first : last + 1, query.relative_state
            ]
            self.candidate_cache[key] = tuple(
                int(item)
                for item in np.flatnonzero(
                    np.any(counts >= self.config.minimum_support, axis=0)
                )
            )
        return self.candidate_cache[key]

    def calibration(self, statistics: dict[str, object]) -> dict[str, float | int]:
        if (
            statistics["patch"] != self.patch
            or tuple(statistics["item_ids"]) != self.item_ids
        ):
            raise ValueError("Calibration evidence does not match the model catalog")
        item_index = {item: index for index, item in enumerate(self.item_ids)}
        squared_error = 0.0
        state_error = 0.0
        hero_error = 0.0
        log_loss = 0.0
        observations = 0
        supported = 0
        for hero, wealth, relative, item, count, wins in statistics["item_counts"]:
            if int(hero) not in self.hero_index or int(item) not in item_index:
                continue
            key = (
                self.hero_index[int(hero)],
                int(wealth),
                int(relative),
                item_index[int(item)],
            )
            probability = min(1 - 1e-12, max(1e-12, float(self.means[key])))
            state_probability = float(self.baselines[key[:-1]])
            hero_probability = float(self.hero_priors[key[0]])
            squared_error += (
                wins * (1 - probability) ** 2 + (count - wins) * probability**2
            )
            state_error += (
                wins * (1 - state_probability) ** 2
                + (count - wins) * state_probability**2
            )
            hero_error += (
                wins * (1 - hero_probability) ** 2
                + (count - wins) * hero_probability**2
            )
            log_loss -= wins * math.log(probability) + (count - wins) * math.log1p(
                -probability
            )
            observations += int(count)
            supported += (
                int(count) if self.counts[key] >= self.config.minimum_support else 0
            )
        return {
            "observations": observations,
            "supported_observations": supported,
            "brier_score": squared_error / max(1, observations),
            "state_baseline_brier": state_error / max(1, observations),
            "hero_baseline_brier": hero_error / max(1, observations),
            "log_loss": log_loss / max(1, observations),
        }
