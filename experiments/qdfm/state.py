"""Reconstruct strictly pre-purchase state; future outcomes are never features."""

from __future__ import annotations

import bisect
import json
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True)
class Purchase:
    item: int
    time: int
    sold: int


class Catalog:
    def __init__(self, source: Path) -> None:
        rows = json.loads((source / "raw/items.json").read_text())
        all_rows = json.loads((source / "raw/items-all.json").read_text())
        self.ids = sorted(int(row["id"]) for row in rows)
        self.index = {item: index for index, item in enumerate(self.ids)}
        self.names = {int(row["id"]): row["name"] for row in rows}
        self.costs = {int(row["id"]): row["cost"] for row in rows}
        classes = {row["class_name"]: int(row["id"]) for row in rows}
        self.components = {
            int(row["id"]): tuple(
                classes[component]
                for component in row.get("component_items", [])
                if component in classes
            )
            for row in rows
        }
        self.ancestors = {item: self._ancestors(item) for item in self.ids}
        self.abilities = {
            int(row["id"]) for row in all_rows if row.get("type") == "ability"
        }
        hero_rows = json.loads((source / "raw/heroes.json").read_text())
        self.heroes = sorted(int(row["id"]) for row in hero_rows)
        self.hero_index = {hero: index for index, hero in enumerate(self.heroes)}

    def _ancestors(self, item: int) -> frozenset[int]:
        result = set(self.components[item])
        for component in self.components[item]:
            result.update(self._ancestors(component))
        return frozenset(result)

    def purchases(
        self, ids: list[int], times: list[int], sold: list[int]
    ) -> list[Purchase]:
        if not len(ids) == len(times) == len(sold):
            raise ValueError("Purchase arrays have different lengths")
        return sorted(
            (
                Purchase(int(item), int(t), int(s or 0))
                for item, t, s in zip(ids, times, sold, strict=True)
                if item in self.index
            ),
            key=lambda event: (event.time, len(self.ancestors[event.item]), event.item),
        )

    def inventory(self, purchases: list[Purchase], time: int) -> tuple[int, ...]:
        owned = {}
        for event in purchases:
            if event.time >= time:
                break
            owned = {
                item: sale
                for item, sale in owned.items()
                if sale <= 0 or sale > event.time
            }
            for component in self.ancestors[event.item]:
                owned.pop(component, None)
            owned[event.item] = event.sold
        return tuple(
            sorted(item for item, sale in owned.items() if sale <= 0 or sale >= time)
        )

    def legal_bundle(self, owned: tuple[int, ...], bundle: tuple[int, ...]) -> bool:
        inventory = set(owned)
        # The catalog supplies dependency order inside a simultaneous basket.
        # It supplies no chronological order between unrelated items.
        for item in sorted(bundle, key=lambda value: len(self.ancestors[value])):
            if item in inventory or any(
                item in self.ancestors[parent] for parent in inventory
            ):
                return False
            inventory.difference_update(self.ancestors[item])
            inventory.add(item)
        return True


@dataclass
class Player:
    slot: int
    hero: int
    team: int
    times: list[int]
    wealth: list[int]
    purchases: list[Purchase]

    def wealth_before(self, time: int) -> tuple[int, int] | None:
        index = bisect.bisect_left(self.times, time) - 1
        if index < 0:
            return None
        return self.wealth[index], time - self.times[index]


def groups(
    purchases: list[Purchase], start: int = 600
) -> list[tuple[int, tuple[int, ...]]]:
    grouped = defaultdict(list)
    for event in purchases:
        if event.time >= start:
            grouped[event.time].append(event.item)
    return [(time, tuple(sorted(items))) for time, items in sorted(grouped.items())]


def inventory_features(
    catalog: Catalog,
    players: list[Player],
    focal: Player,
    time: int,
    owned: tuple[int, ...],
) -> np.ndarray:
    item_features = np.zeros((3, len(catalog.ids)), dtype=np.float32)
    for item in owned:
        item_features[0, catalog.index[item]] = 1
    for purchase in focal.purchases:
        if purchase.time < time:
            item_features[1, catalog.index[purchase.item]] += 0.5
    for player in players:
        if player.team != focal.team:
            for item in catalog.inventory(player.purchases, time):
                item_features[2, catalog.index[item]] += 1 / 6
    return item_features


def features(
    catalog: Catalog,
    players: list[Player],
    focal: Player,
    time: int,
    badge: int,
    lane: int,
) -> tuple[np.ndarray, tuple[int, ...]] | None:
    observations = [player.wealth_before(time) for player in players]
    if len(players) != 12 or any(value is None for value in observations):
        return None
    wealth = np.array([value[0] for value in observations], dtype=np.float32)
    ages = np.array([value[1] for value in observations], dtype=np.float32)
    if ages.max() > 300:
        return None
    own_index = next(
        index for index, player in enumerate(players) if player.slot == focal.slot
    )
    allied = np.array([player.team == focal.team for player in players])
    other = np.arange(12) != own_index
    own = wealth[own_index]
    median = np.median(wealth[other])
    team_wealth, enemy_wealth = wealth[allied].sum(), wealth[~allied].sum()
    old = focal.wealth_before(time - 300)
    growth = (own - old[0]) / 10000 if old else 0.0
    numeric = [
        time / 2400,
        own / 50000,
        median / 50000,
        (own - median) / max(float(median), 1000),
        float((wealth[other] < own).mean()),
        (team_wealth - enemy_wealth) / max(float(team_wealth + enemy_wealth), 1000),
        own / max(float(team_wealth), 1000),
        (own - wealth[~allied].max()) / max(float(wealth[~allied].max()), 1000),
        growth,
        float(old is not None),
        ages[own_index] / 300,
        ages.max() / 300,
        badge / 115,
        lane / 4,
    ]
    hero_features = np.zeros((3, len(catalog.heroes)), dtype=np.float32)
    hero_features[0, catalog.hero_index[focal.hero]] = 1
    for player in players:
        if player.slot != focal.slot:
            hero_features[
                1 if player.team == focal.team else 2, catalog.hero_index[player.hero]
            ] = 1
    owned = catalog.inventory(focal.purchases, time)
    item_features = inventory_features(catalog, players, focal, time, owned)
    array = np.concatenate((
        np.array(numeric, dtype=np.float32),
        hero_features.flatten(),
        item_features.flatten(),
    ))
    return array, owned
