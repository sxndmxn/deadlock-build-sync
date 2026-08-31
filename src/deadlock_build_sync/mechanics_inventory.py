from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .mechanics_assets import (
    BASE_INVENTORY_SLOTS,
    MAX_ACTIVE_ITEMS,
    MAX_FLEX_SLOTS,
    MechanicsError,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from .mechanics_abilities import AbilityDefinition
    from .mechanics_items import ItemGraph


@dataclass(frozen=True)
class InventoryState:
    owned: tuple[int, ...] = ()
    unlocked_flex_slots: int = 0

    def __post_init__(self) -> None:
        """Validate the flex-slot domain.

        Raises:
            MechanicsError: If the state claims an impossible flex count.

        """
        if not 0 <= self.unlocked_flex_slots <= MAX_FLEX_SLOTS:
            raise MechanicsError("unlocked flex slots must be between zero and three")


def purchase_item(
    graph: ItemGraph,
    state: InventoryState,
    item_id: int,
    *,
    required_flex_slots: int = 0,
) -> InventoryState:
    """Apply one legal purchase including direct component consumption.

    Returns:
        The post-purchase inventory.

    Raises:
        MechanicsError: If availability, duplicate, flex, slot, or active limits fail.

    """
    node = graph.require(item_id)
    if required_flex_slots > state.unlocked_flex_slots:
        raise MechanicsError("purchase requires unavailable flex capacity")
    owned = list(state.owned)
    count = owned.count(item_id)
    if (node.unique and count) or count >= node.max_count:
        raise MechanicsError(f"item {node.name} exceeds its ownership limit")
    for component_id in graph.components[item_id]:
        if component_id in owned:
            owned.remove(component_id)
    owned.append(item_id)
    capacity = BASE_INVENTORY_SLOTS + state.unlocked_flex_slots
    if len(owned) > capacity:
        raise MechanicsError(f"purchase exceeds {capacity} available item slots")
    active_count = sum(graph.require(owned_id).active for owned_id in owned)
    if active_count > MAX_ACTIVE_ITEMS:
        raise MechanicsError("purchase exceeds four active-item bindings")
    return InventoryState(tuple(owned), state.unlocked_flex_slots)


@dataclass(frozen=True)
class _ComponentPlan:
    item_ids: tuple[int, ...]
    dependencies: tuple[frozenset[int], ...]


class _ComponentPlanner:
    def __init__(self, graph: ItemGraph) -> None:
        self.graph = graph
        self.planned_ids: list[int] = []
        self.dependencies: list[set[int]] = []
        self.consumed_by: dict[int, int] = {}
        self.owned_actions: dict[int, int] = {}
        self.last_action_by_item: dict[int, int] = {}
        self.state = InventoryState()

    def plan(self, item_id: int) -> int:
        if item_id in self.state.owned:
            try:
                return self.owned_actions[item_id]
            except KeyError as error:
                raise MechanicsError(
                    f"owned item {item_id} has no planned purchase action"
                ) from error

        component_actions = tuple(
            self.plan(component_id) for component_id in self.graph.components[item_id]
        )
        action_index = len(self.planned_ids)
        action_dependencies = set(component_actions)
        previous_action = self.last_action_by_item.get(item_id)
        if previous_action is not None:
            consumer = self.consumed_by.get(previous_action)
            if consumer is None:
                raise MechanicsError(
                    f"item {item_id} cannot be rebought before its prior copy is consumed"
                )
            action_dependencies.add(consumer)

        missing = [
            component_id
            for component_id in self.graph.components[item_id]
            if component_id not in self.state.owned
        ]
        if missing:
            raise MechanicsError(
                f"planned item {item_id} is missing components {missing}"
            )
        self.state = purchase_item(self.graph, self.state, item_id)
        self.planned_ids.append(item_id)
        self.dependencies.append(action_dependencies)
        for component_id, component_action in zip(
            self.graph.components[item_id], component_actions, strict=True
        ):
            self.consumed_by[component_action] = action_index
            self.owned_actions.pop(component_id, None)
        self.owned_actions[item_id] = action_index
        self.last_action_by_item[item_id] = action_index
        return action_index

    def build(self, target_ids: tuple[int, ...]) -> _ComponentPlan:
        final_actions: list[int] = []
        for item_id in target_ids:
            action_index = self.plan(item_id)
            if action_index in final_actions:
                raise MechanicsError(f"final item {item_id} was already scheduled")
            if final_actions:
                self.dependencies[action_index].add(final_actions[-1])
            final_actions.append(action_index)
        if set(self.state.owned) != set(target_ids):
            raise MechanicsError(
                "planned component path does not end in final inventory"
            )
        return _ComponentPlan(
            tuple(self.planned_ids),
            tuple(frozenset(required) for required in self.dependencies),
        )


def _plan_component_actions(
    graph: ItemGraph, target_ids: tuple[int, ...]
) -> _ComponentPlan:
    return _ComponentPlanner(graph).build(target_ids)


class _ComponentScheduleSearch:
    def __init__(
        self,
        graph: ItemGraph,
        plan: _ComponentPlan,
        target_ids: tuple[int, ...],
        priorities: Mapping[int, tuple[float, float, int]],
    ) -> None:
        self.graph = graph
        self.plan = plan
        self.target_ids = target_ids
        self.priorities = priorities
        self.failed_states: set[tuple[frozenset[int], tuple[int, ...], int]] = set()

    def _ready_actions(self, completed: frozenset[int]) -> list[int]:
        return sorted(
            (
                index
                for index, required in enumerate(self.plan.dependencies)
                if index not in completed and required <= completed
            ),
            key=lambda index: (
                *self.priorities.get(
                    self.plan.item_ids[index],
                    (
                        float("inf"),
                        float("inf"),
                        self.plan.item_ids[index],
                    ),
                ),
                index,
            ),
        )

    def search(
        self,
        completed: frozenset[int],
        state: InventoryState,
    ) -> tuple[int, ...] | None:
        if len(completed) == len(self.plan.item_ids):
            return () if set(state.owned) == set(self.target_ids) else None
        state_key = (
            completed,
            tuple(sorted(state.owned)),
            state.unlocked_flex_slots,
        )
        if state_key in self.failed_states:
            return None
        for action_index in self._ready_actions(completed):
            item_id = self.plan.item_ids[action_index]
            if any(
                component_id not in state.owned
                for component_id in self.graph.components[item_id]
            ):
                continue
            try:
                next_state = purchase_item(self.graph, state, item_id)
            except MechanicsError:
                continue
            suffix = self.search(completed | {action_index}, next_state)
            if suffix is not None:
                return (action_index, *suffix)
        self.failed_states.add(state_key)
        return None


def _search_component_schedule(
    graph: ItemGraph,
    plan: _ComponentPlan,
    target_ids: tuple[int, ...],
    priorities: Mapping[int, tuple[float, float, int]],
) -> tuple[int, ...] | None:
    return _ComponentScheduleSearch(graph, plan, target_ids, priorities).search(
        frozenset(), InventoryState()
    )


def schedule_component_path(
    graph: ItemGraph,
    targets: Sequence[int],
    priorities: Mapping[int, tuple[float, float, int]],
) -> tuple[int, ...]:
    """Schedule a chronological, legal purchase path for a final inventory.

    Purchase timing ranks every action, while component dependencies, final-item
    order, inventory capacity, active-item limits, and consumed-component rebuys
    remain hard constraints.

    Returns:
        Item IDs in executable left-to-right purchase order.

    Raises:
        MechanicsError: If no legal schedule reaches the requested inventory.

    """
    target_ids = tuple(targets)
    if not target_ids:
        raise MechanicsError("component schedule has no final inventory targets")
    if len(set(target_ids)) != len(target_ids):
        raise MechanicsError("component schedule final inventory contains duplicates")
    for item_id in target_ids:
        graph.require(item_id)

    plan = _plan_component_actions(graph, target_ids)
    scheduled_actions = _search_component_schedule(graph, plan, target_ids, priorities)
    if scheduled_actions is None:
        names = ", ".join(graph.require(item_id).name for item_id in target_ids)
        raise MechanicsError(f"no legal chronological component schedule for {names}")
    return tuple(plan.item_ids[index] for index in scheduled_actions)


def sell_item(graph: ItemGraph, state: InventoryState, item_id: int) -> InventoryState:
    """Sell one currently owned item.

    Returns:
        The post-sale inventory.

    Raises:
        MechanicsError: If the item is unknown or not owned.

    """
    graph.require(item_id)
    owned = list(state.owned)
    if item_id not in owned:
        raise MechanicsError(f"cannot sell unowned item {item_id}")
    owned.remove(item_id)
    return InventoryState(tuple(owned), state.unlocked_flex_slots)


def validate_imbue(
    definitions: dict[int, AbilityDefinition],
    learned_abilities: set[int],
    ability_id: int,
    *,
    required_qualifier: str | None = None,
    allow_ultimate: bool = True,
) -> None:
    """Validate an item-to-ability imbue against current learned mechanics.

    Raises:
        MechanicsError: If the target is unlearned, disallowed, or unqualified.

    """
    definition = definitions.get(ability_id)
    if definition is None or ability_id not in learned_abilities:
        raise MechanicsError("imbue target must be a current learned ability")
    if definition.ultimate and not allow_ultimate:
        raise MechanicsError("this item cannot imbue an ultimate ability")
    if required_qualifier and required_qualifier not in definition.qualifiers:
        raise MechanicsError(f"ability {ability_id} is not proven {required_qualifier}")
