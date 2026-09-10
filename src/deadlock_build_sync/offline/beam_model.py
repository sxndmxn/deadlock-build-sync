"""Estimate purchase scores from discovery observations only."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from deadlock_build_sync.guide_generator import BEAM_SETTINGS

from .sql_resources import load_sql

if TYPE_CHECKING:
    import duckdb

    from .discovery_data import HeroDiscoveryData


class BeamItemModel:
    def __init__(
        self,
        rows: list[tuple[int, int, int, int, int]],
        hero_wins: int,
        hero_matches: int,
    ) -> None:
        self.cells = {
            (wealth, state, item): (count, wins)
            for wealth, state, item, count, wins in rows
        }
        totals: dict[tuple[int, int], tuple[int, int]] = {}
        for wealth, state, _item, count, wins in rows:
            old_count, old_wins = totals.get((wealth, state), (0, 0))
            totals[wealth, state] = old_count + count, old_wins + wins
        prior = (hero_wins + 1) / (hero_matches + 2)
        self.baselines = {
            key: (wins + 20 * prior) / (count + 20)
            for key, (count, wins) in totals.items()
        }
        self.prior = prior
        self.cache: dict[tuple[int, int, int], tuple[float, int]] = {}

    def estimate(self, wealth: int, state: int, item: int) -> tuple[float, int]:
        key = min(11, wealth // 4000), state, item
        if key not in self.cache:
            count, wins = self.cells.get(key, (0, 0))
            baseline = self.baselines.get(key[:2], self.prior)
            strength = BEAM_SETTINGS["prior_strength"]
            total = count + strength
            alpha = wins + strength * baseline
            beta = total - alpha
            variance = alpha * beta / (total * total * (total + 1))
            utility = (
                alpha / total
                - baseline
                - BEAM_SETTINGS["uncertainty_multiplier"] * math.sqrt(variance)
            )
            self.cache[key] = utility, count
        return self.cache[key]

    def score(
        self, wealth: int, state: int, item: int, cost: int, depth: int
    ) -> float | None:
        utility, support = self.estimate(wealth, state, item)
        if support < BEAM_SETTINGS["minimum_item_support"]:
            return None
        scale = max(cost, 800) / 1600
        return (
            utility
            * BEAM_SETTINGS["discount"] ** depth
            / scale ** BEAM_SETTINGS["cost_exponent"]
        )


def load_beam_model(
    connection: duckdb.DuckDBPyConnection,
    values: HeroDiscoveryData,
    minimum_badge: int,
    maximum_badge: int,
) -> BeamItemModel:
    rows = connection.execute(
        load_sql("beam/select_item_counts.sql"),
        {
            "hero": values.hero,
            "minimum_badge": minimum_badge,
            "maximum_badge": maximum_badge,
        },
    ).fetchall()
    discovery = values.fold_mask("discovery")
    return BeamItemModel(rows, int(values.won[discovery].sum()), int(discovery.sum()))
