"""Replan optional purchases from actual inventory without selling core items."""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

from .mechanics import (
    BASE_INVENTORY_SLOTS,
    InventoryState,
    MechanicsError,
    purchase_item,
)
from .purchase_guidance_types import PurchasePlan, PurchaseState, PurchaseStep

if TYPE_CHECKING:
    from .mechanics import ItemGraph


def covered(graph: ItemGraph, item: int, owned: tuple[int, ...]) -> bool:
    return item in owned or any(
        item in graph.transitive_components(parent) for parent in owned
    )


class PurchasePlanner:
    def __init__(self, graph: ItemGraph, owned: tuple[int, ...], flex: int) -> None:
        if isinstance(flex, bool) or not isinstance(flex, int):
            raise MechanicsError("Flex slots must be an integer")
        self.graph = graph
        self.state = InventoryState(owned, flex)
        for item, count in Counter(owned).items():
            if isinstance(item, bool) or not isinstance(item, int):
                raise MechanicsError("Owned item IDs must be integers")
            node = graph.require(item)
            if count > node.max_count or (node.unique and count > 1):
                raise MechanicsError("Inventory exceeds an item's ownership limit")
        if len(owned) > BASE_INVENTORY_SLOTS + flex:
            raise MechanicsError("Current inventory exceeds available slots")
        if sum(graph.require(item).active for item in owned) > 4:
            raise MechanicsError("Current inventory exceeds four active bindings")
        self.actions: list[PurchaseStep] = []
        self.total = 0

    def acquire(self, item: int, *, exact: bool = False) -> None:
        satisfied = (
            item in self.state.owned
            if exact
            else covered(self.graph, item, self.state.owned)
        )
        if satisfied:
            return
        for component in self.graph.components[item]:
            self.acquire(component, exact=True)
        cash = self.graph.incremental_cash_cost(item, self.state.owned)
        consumed = tuple(
            part for part in self.graph.components[item] if part in self.state.owned
        )
        self.state = purchase_item(self.graph, self.state, item)
        self.total += cash
        self.actions.append(
            PurchaseStep(
                item,
                self.graph.require(item).name,
                cash,
                self.total,
                consumed,
                self.state.owned,
            )
        )

    def result(self, liquid_souls: int | None) -> PurchasePlan:
        shortage = (
            max(0, self.actions[0].incremental_cost - liquid_souls)
            if self.actions and liquid_souls is not None
            else None
        )
        decision = (
            "complete"
            if not self.actions
            else "save"
            if shortage
            else "buy"
            if liquid_souls is not None
            else "check cash"
        )
        return PurchasePlan(
            tuple(self.actions), self.state.owned, self.total, decision, shortage
        )


def validate_positions(
    graph: ItemGraph,
    path: tuple[int, ...],
    positions: dict[int, int],
    owned: tuple[int, ...],
) -> None:
    for item, index in positions.items():
        if isinstance(item, bool) or not isinstance(item, int):
            raise TypeError("Selected item IDs must be integers")
        if (
            isinstance(index, bool)
            or not isinstance(index, int)
            or not 0 <= index <= len(path)
        ):
            raise ValueError(
                "Purchase position must be an integer within the default path"
            )
        components = graph.transitive_components(item)
        remaining = {
            value for value in path[index:] if not covered(graph, value, owned)
        }
        if remaining.intersection(components):
            raise ValueError("Purchase position precedes a required core item")
        if any(
            component in positions and positions[component] > index
            for component in components
        ):
            raise ValueError("Selected upgrade precedes its selected component")


def plan_purchases(
    graph: ItemGraph,
    path: tuple[int, ...],
    core: tuple[int, ...],
    positions: dict[int, int],
    *,
    state: PurchaseState | None = None,
) -> PurchasePlan:
    """Return a legal core-preserving route, including consumed-component rebuys.

    Returns:
        The full remaining route and the affordable next action.

    Raises:
        ValueError: If a position or liquid soul value is invalid.
        MechanicsError: If inventory or the resulting path is illegal.

    """
    state = state or PurchaseState()
    liquid_souls = state.liquid_souls
    if liquid_souls is not None and (
        isinstance(liquid_souls, bool)
        or not isinstance(liquid_souls, int)
        or liquid_souls < 0
    ):
        raise ValueError("Liquid souls must be a nonnegative integer")
    planner = PurchasePlanner(graph, state.owned, state.flex)
    validate_positions(graph, path, positions, state.owned)
    selected = sorted(
        positions,
        key=lambda item: (
            positions[item],
            len(graph.transitive_components(item)),
            item,
        ),
    )
    for index in range(len(path) + 1):
        for item in selected:
            if positions[item] == index:
                planner.acquire(item)
        if index < len(path):
            planner.acquire(path[index])
    if not all(covered(graph, item, planner.state.owned) for item in core):
        raise MechanicsError("Choice abandons the core's upgrade lineages")
    return planner.result(liquid_souls)
