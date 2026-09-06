"""Executable choices and recovery from actual ownership, with catalog accounting."""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

from deadlock_build_sync.build_evidence_types import nondecreasing_window_schedule
from deadlock_build_sync.mechanics import (
    BASE_INVENTORY_SLOTS,
    InventoryState,
    MechanicsError,
    purchase_item,
    schedule_component_path,
)

from experiments.build_guides.evidence import timing_policy

if TYPE_CHECKING:
    from deadlock_build_sync.mechanics import ItemGraph


def covered(graph: ItemGraph, item: int, owned: tuple[int, ...]) -> bool:
    return item in owned or any(
        item in graph.transitive_components(parent) for parent in owned
    )


def buy(graph: ItemGraph, state: InventoryState, item: int, role: str) -> tuple:
    consumed = [part for part in graph.components[item] if part in state.owned]
    cash = graph.incremental_cash_cost(item, state.owned)
    credit = graph.credited_component_value(item, state.owned)
    state = purchase_item(graph, state, item)
    return state, {
        "item_id": item,
        "name": graph.require(item).name,
        "role": role,
        "incremental_cost": cash,
        "component_credit": credit,
        "consumed_items": consumed,
        "owned_after": list(state.owned),
        "slots_after": len(state.owned),
        "actives_after": sum(graph.require(value).active for value in state.owned),
    }


def replay(graph: ItemGraph, path: list[int], core: list[int]) -> list[dict]:
    state, actions, total = InventoryState(), [], 0
    for item in path:
        state, action = buy(
            graph, state, item, "core" if item in core else "required component"
        )
        total += action["incremental_cost"]
        action["cumulative_cost"] = total
        actions.append(action)
    if set(state.owned) != set(core) or total != sum(
        graph.require(item).cost for item in core
    ):
        raise MechanicsError("Default path does not reach the exact core and cost")
    return actions


def default_path(row: dict, graph: ItemGraph, evidence: dict) -> dict:
    order = row["path"]["order"]
    if not order:
        return {"actions": [], "ready": False, "reason": "No supported core order"}
    priorities, bounds = timing_policy(evidence["items"])
    try:
        path = list(schedule_component_path(graph, order, priorities))
        if len(path) != len(set(path)):
            return {
                "actions": [],
                "ready": False,
                "reason": "Static guide would repeat a consumed component card",
            }
        actions = replay(graph, path, row["items"])
    except MechanicsError as error:
        return {"actions": [], "ready": False, "reason": str(error)}
    checkpoints = nondecreasing_window_schedule(path, bounds)
    for index, action in enumerate(actions):
        action["timing"] = evidence["items"].get(action["item_id"])
        action["minimum_observed_net_worth"] = (
            checkpoints[index]
            if checkpoints is not None and action["item_id"] in bounds
            else None
        )
    return {
        "actions": actions,
        "ready": checkpoints is not None,
        "reason": None
        if checkpoints is not None
        else "Core order and observed component wealth windows cannot be reconciled",
        "timing_basis": "first ownership among discovery core owners",
    }


class Planner:
    def __init__(self, graph: ItemGraph, owned: list[int], flex: int) -> None:
        self.graph = graph
        if isinstance(flex, bool) or not isinstance(flex, int):
            raise MechanicsError("Flex slots must be an integer")
        self.state = InventoryState(tuple(owned), flex)
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
        self.actions: list[dict] = []

    def acquire(self, item: int, role: str, *, exact: bool = False) -> None:
        satisfied = (
            item in self.state.owned
            if exact
            else covered(self.graph, item, self.state.owned)
        )
        if satisfied:
            return
        # A sibling upgrade needs a fresh shared component after consumption.
        for component in self.graph.components[item]:
            self.acquire(component, "required component", exact=True)
        self.state, action = buy(self.graph, self.state, item, role)
        self.actions.append(action)


def prepare_choices(guide: dict, selected: list[int], liquid_souls: int | None) -> dict:
    if liquid_souls is not None and (
        isinstance(liquid_souls, bool)
        or not isinstance(liquid_souls, int)
        or liquid_souls < 0
    ):
        raise ValueError("Liquid souls must be a nonnegative integer")
    if not isinstance(selected, list) or any(
        isinstance(item, bool) or not isinstance(item, int) for item in selected
    ):
        raise ValueError("Selected item IDs must be integers in a list")
    if len(selected) != len(set(selected)):
        raise ValueError("A choice was selected twice")
    cards = {card["item_id"]: card for card in guide["choices"]}
    if any(item not in cards for item in selected):
        raise ValueError("Selection is outside this identity's item pool")
    if not guide["default_path"]["ready"]:
        raise MechanicsError("Guide has no timing-feasible default path")
    return cards


def choice_positions(
    guide: dict,
    selected: list[int],
    cards: dict,
    overrides: dict | None,
    graph: ItemGraph,
    owned: tuple[int, ...],
) -> dict[int, int]:
    overrides = {} if overrides is None else overrides
    if not isinstance(overrides, dict):
        raise TypeError("Placement overrides must map item IDs to purchase positions")
    allowed = {str(item) for item in selected}
    if set(overrides) - allowed:
        raise ValueError("Placement overrides must refer to selected item IDs")
    positions = {}
    for item in selected:
        placement = cards[item]["placement"]
        index = overrides.get(str(item), placement["after_step"])
        if index is None:
            raise ValueError(
                f"Timing unknown for {cards[item]['name']}; supply placement_overrides"
            )
        if (
            isinstance(index, bool)
            or not isinstance(index, int)
            or not 0 <= index <= len(guide["default_path"]["actions"])
        ):
            raise ValueError(
                "Purchase position must be an integer within the default path"
            )
        remaining_core = {
            step["item_id"]
            for step in guide["default_path"]["actions"][index:]
            if not covered(graph, step["item_id"], owned)
        }
        if remaining_core.intersection(cards[item]["upgrades_core"]):
            raise ValueError(
                f"Purchase position precedes a required core item for {cards[item]['name']}"
            )
        positions[item] = index
    return positions


def validate_choice_order(graph: ItemGraph, positions: dict[int, int]) -> None:
    for item, index in positions.items():
        for component in graph.transitive_components(item):
            if component in positions and positions[component] > index:
                raise ValueError("Selected upgrade precedes its selected component")


def plan(
    graph: ItemGraph,
    guide: dict,
    selected: list[int],
    *,
    owned: list[int] | None = None,
    liquid_souls: int | None = None,
    flex: int = 0,
    placement_overrides: dict | None = None,
) -> dict:
    cards = prepare_choices(guide, selected, liquid_souls)
    planner = Planner(graph, owned or [], flex)
    positions = choice_positions(
        guide, selected, cards, placement_overrides, graph, planner.state.owned
    )
    validate_choice_order(graph, positions)
    selected = sorted(
        selected,
        key=lambda item: (
            positions[item],
            len(graph.transitive_components(item)),
            cards[item]["purchase_evidence"]["time_seconds_q25_q50_q75"][1],
            item,
        ),
    )
    path = guide["default_path"]["actions"]
    for index in range(len(path) + 1):
        for item in selected:
            if positions[item] == index:
                planner.acquire(item, "optional choice")
        if index < len(path):
            planner.acquire(path[index]["item_id"], path[index]["role"])
    if not all(covered(graph, item, planner.state.owned) for item in guide["core_ids"]):
        raise MechanicsError("Choice abandons the discovered core's upgrade lineages")
    return {
        **summarize_plan(planner, liquid_souls),
        "selected_placements": {
            str(item): {
                "after_step": positions[item],
                "basis": "explicit override"
                if str(item) in (placement_overrides or {})
                else "observed purchase timing",
            }
            for item in selected
        },
    }


def summarize_plan(planner: Planner, liquid_souls: int | None) -> dict:
    total = 0
    for action in planner.actions:
        total += action["incremental_cost"]
        action["cumulative_cost"] = total
    next_action = planner.actions[0] if planner.actions else None
    shortage = (
        max(0, next_action["incremental_cost"] - liquid_souls)
        if next_action and liquid_souls is not None
        else None
    )
    return {
        "actions": planner.actions,
        "final_inventory": list(planner.state.owned),
        "remaining_cost": total,
        "next_action": next_action,
        "decision": "complete"
        if next_action is None
        else "save"
        if shortage
        else "buy"
        if liquid_souls is not None
        else "check cash",
        "save_souls": shortage,
        "relative_wealth_policy": "No validated ahead/behind preference; cash governs affordability",
    }
