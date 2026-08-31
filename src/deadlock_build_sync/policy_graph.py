from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .policy_claims import PolicyError


class NodeKind(StrEnum):
    PURCHASE = "purchase"
    CHOICE = "choice"
    SELL = "sell"
    ABILITY = "ability"
    WAIT = "wait"
    OBJECTIVE_GATE = "objective_gate"
    END = "end"


class GuardOperator(StrEnum):
    EQUALS = "eq"
    NOT_EQUALS = "ne"
    AT_LEAST = "gte"
    AT_MOST = "lte"
    CONTAINS = "contains"
    EXISTS = "exists"


_OBSERVABLE_FIELDS: dict[str, type[object] | tuple[type[object], ...]] = {
    "enemy.heroes": (list, tuple, set),
    "enemy.lane_heroes": (list, tuple, set),
    "enemy.threats": (list, tuple, set),
    "enemy.items": (list, tuple, set),
    "ally.heroes": (list, tuple, set),
    "ally.missing_function": str,
    "inventory.items": (list, tuple, set),
    "inventory.components": (list, tuple, set),
    "inventory.open_slots": int,
    "inventory.active_bindings": int,
    "inventory.flex_slots": int,
    "clock_s": int,
    "level": int,
    "ability_points": int,
    "economy.liquid": int,
    "economy.net_worth": int,
    "economy.relative_state": str,
    "objectives.available": (list, tuple, set),
    "objectives.flex_slots": int,
    "cooldowns.ready": (list, tuple, set),
    "cohort.match_mode": str,
    "cohort.rank_badge": int,
    "epoch.identity": str,
}


@dataclass(frozen=True)
class Guard:
    field: str
    operator: GuardOperator
    value: object = None

    def __post_init__(self) -> None:
        """Type-check a guard against the versioned observable-state schema.

        Raises:
            PolicyError: If the field, operator, or comparison value is invalid.

        """
        expected = _OBSERVABLE_FIELDS.get(self.field)
        if expected is None:
            raise PolicyError(f"guard references unknown observable field {self.field}")
        if self.operator == GuardOperator.EXISTS:
            return
        if self.operator in {GuardOperator.AT_LEAST, GuardOperator.AT_MOST}:
            if expected is not int or not isinstance(self.value, int):
                raise PolicyError(f"guard {self.field} requires an integer comparison")
            return
        if self.operator == GuardOperator.CONTAINS:
            if expected != (list, tuple, set):
                raise PolicyError(f"guard {self.field} is not a collection")
            return
        if not isinstance(self.value, expected):
            raise PolicyError(f"guard {self.field} has an incompatible value")

    def matches(self, state: dict[str, object]) -> bool:
        """Evaluate this guard against flattened observable state.

        Returns:
            Whether the condition holds.

        """
        if self.operator == GuardOperator.EXISTS:
            return self.field in state
        current = state.get(self.field)
        if self.operator == GuardOperator.EQUALS:
            return current == self.value
        if self.operator == GuardOperator.NOT_EQUALS:
            return current != self.value
        if self.operator == GuardOperator.AT_LEAST:
            return (
                isinstance(current, int)
                and isinstance(self.value, int)
                and current >= self.value
            )
        if self.operator == GuardOperator.AT_MOST:
            return (
                isinstance(current, int)
                and isinstance(self.value, int)
                and current <= self.value
            )
        if self.operator == GuardOperator.CONTAINS:
            return isinstance(current, (list, tuple, set)) and self.value in current
        return False

    def as_dict(self) -> dict[str, object]:
        from .policy_codec import unstructure_guard

        return unstructure_guard(self)

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> Guard:
        """Decode a typed observable-state guard.

        Returns:
            A validated guard.

        Raises:
            PolicyError: If required fields or the operator are invalid.

        """
        from .policy_codec import structure_guard

        return structure_guard(value)


@dataclass(frozen=True)
class Branch:
    next_id: str
    guard: Guard | None = None
    priority: int | None = None
    additional_guards: tuple[Guard, ...] = ()

    @property
    def is_default(self) -> bool:
        return self.guard is None and not self.additional_guards

    @property
    def guards(self) -> tuple[Guard, ...]:
        """Every condition in this branch's conjunction."""
        return (
            (self.guard, *self.additional_guards)
            if self.guard is not None
            else self.additional_guards
        )

    def matches(self, state: dict[str, object]) -> bool:
        """Return whether every observable condition matches.

        Returns:
            Whether all conditions match the current observable state.

        """
        return bool(self.guards) and all(guard.matches(state) for guard in self.guards)

    def as_dict(self) -> dict[str, object]:
        from .policy_codec import unstructure_branch

        return unstructure_branch(self)

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> Branch:
        """Decode one choice branch.

        Returns:
            A branch with a typed guard or explicit default.

        Raises:
            PolicyError: If the branch has no valid successor/guard.

        """
        from .policy_codec import structure_branch

        return structure_branch(value)


@dataclass(frozen=True)
class PolicyNode:
    node_id: str
    kind: NodeKind
    next_id: str | None = None
    evidence_ref: str | None = None
    item_id: int | None = None
    ability_id: int | None = None
    level: int | None = None
    branches: tuple[Branch, ...] = ()
    optional: bool = False
    required_flex_slots: int = 0
    sell_priority: int | None = None
    imbue_target_ability_id: int | None = None
    imbue_qualifier: str | None = None
    allow_ultimate_imbue: bool = True
    unlocks_flex_slots: int | None = None
    earliest_time_s: int | None = None
    latest_time_s: int | None = None
    recalculation_next: str | None = None
    annotation: str = ""

    def __post_init__(self) -> None:
        """Validate fields required by this node kind.

        Raises:
            PolicyError: If kind-specific fields are missing or contradictory.

        """
        if not self.node_id.strip():
            raise PolicyError("policy node id must not be empty")
        _validate_node_action_fields(self)
        _validate_node_branches(self)
        _validate_node_constraints(self)

    def successors(self) -> tuple[str, ...]:
        """Return every graph successor.

        Returns:
            Direct node IDs reached from this node.

        """
        if self.branches:
            return tuple(branch.next_id for branch in self.branches)
        return (self.next_id,) if self.next_id is not None else ()

    def as_dict(self) -> dict[str, object]:
        from .policy_codec import unstructure_policy_node

        return unstructure_policy_node(self)

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> PolicyNode:
        """Decode one versioned policy node.

        Returns:
            A typed node for every supported kind.

        Raises:
            PolicyError: If the kind is unknown or fields are malformed.

        """
        from .policy_codec import structure_policy_node

        return structure_policy_node(value)


def _validate_node_action_fields(node: PolicyNode) -> None:
    if node.kind == NodeKind.PURCHASE and node.item_id is None:
        raise PolicyError(f"purchase node {node.node_id} has no item")
    if node.kind == NodeKind.SELL and node.item_id is None:
        raise PolicyError(f"sell node {node.node_id} has no item")
    if node.kind == NodeKind.ABILITY and (
        node.ability_id is None or node.level is None
    ):
        raise PolicyError(f"ability node {node.node_id} is incomplete")


def _validate_node_branches(node: PolicyNode) -> None:
    if node.kind in {NodeKind.CHOICE, NodeKind.OBJECTIVE_GATE}:
        if not node.branches:
            raise PolicyError(f"choice node {node.node_id} has no branches")
    elif node.branches:
        raise PolicyError(f"non-choice node {node.node_id} has branches")


def _validate_node_constraints(node: PolicyNode) -> None:
    if node.kind == NodeKind.END and node.next_id is not None:
        raise PolicyError(f"end node {node.node_id} has a successor")
    if node.required_flex_slots not in range(4):
        raise PolicyError("required flex slots must be between zero and three")
    if node.sell_priority is not None and node.sell_priority <= 0:
        raise PolicyError("sell priority must be positive when present")
    if (
        node.earliest_time_s is not None
        and node.latest_time_s is not None
        and node.earliest_time_s > node.latest_time_s
    ):
        raise PolicyError(f"node {node.node_id} has an inverted time window")
