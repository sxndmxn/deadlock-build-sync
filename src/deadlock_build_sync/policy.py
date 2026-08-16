from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any

from .mechanics import (
    AbilityAction,
    AbilityDefinition,
    InventoryState,
    ItemGraph,
    MechanicsError,
    purchase_item,
    sell_item,
    validate_ability_timeline,
    validate_imbue,
)
from .snapshot import EvidenceUnit, sha256_json


class PolicyError(ValueError):
    """Raised when a build policy is incomplete, ambiguous, stale, or illegal."""


class ClaimClass(StrEnum):
    MECHANICAL = "mechanical"
    DESCRIPTIVE = "descriptive"
    PREDICTIVE = "predictive"
    CAUSAL = "causal"


_LANGUAGE_CEILINGS = {
    ClaimClass.MECHANICAL: frozenset({"grants", "scales", "requires", "can target"}),
    ClaimClass.DESCRIPTIVE: frozenset({
        "observed",
        "associated",
        "adopted",
        "rate",
        "more common",
    }),
    ClaimClass.PREDICTIVE: frozenset({
        "predicts",
        "estimated",
        "conditional",
        "expected",
    }),
    ClaimClass.CAUSAL: frozenset({"causes", "improves", "reduces", "effect"}),
}
_CAUSAL_PHRASES = (
    "causes",
    "adds win rate",
    "improves win rate",
    "increases your chance",
    "item impact",
    "guarantees",
)


@dataclass(frozen=True)
class EvidenceClaim:
    claim_id: str
    claim_class: ClaimClass
    snapshot_id: str
    cohort: dict[str, Any]
    unit: EvidenceUnit
    support: int
    mechanics_refs: tuple[str, ...]
    language_ceiling: frozenset[str]
    numerator: int | None = None
    denominator: int | None = None
    estimate: float | None = None
    interval: tuple[float, float] | None = None
    comparison_baseline: float | None = None

    def __post_init__(self) -> None:
        """Validate claim identity, support, and language strength.

        Raises:
            PolicyError: If required evidence metadata is missing or inconsistent.

        """
        if not self.claim_id.strip() or not self.snapshot_id.strip():
            raise PolicyError("evidence claim identity must not be empty")
        if not self.cohort:
            raise PolicyError(f"claim {self.claim_id} has no cohort")
        if self.support < 0:
            raise PolicyError(f"claim {self.claim_id} has negative support")
        if not self.language_ceiling <= _LANGUAGE_CEILINGS[self.claim_class]:
            raise PolicyError(f"claim {self.claim_id} exceeds its language ceiling")
        if self.claim_class == ClaimClass.MECHANICAL and not self.mechanics_refs:
            raise PolicyError(f"mechanical claim {self.claim_id} has no mechanics refs")
        quantitative = self.estimate is not None or self.interval is not None
        if quantitative and self.support == 0:
            raise PolicyError(f"quantitative claim {self.claim_id} has no support")
        if self.interval is not None:
            lower, upper = self.interval
            if lower > upper:
                raise PolicyError(f"claim {self.claim_id} has an inverted interval")
        if self.denominator is not None and self.denominator != self.support:
            raise PolicyError(f"claim {self.claim_id} denominator differs from support")

    def as_dict(self) -> dict[str, Any]:
        from .policy_codec import unstructure_evidence_claim

        return unstructure_evidence_claim(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> EvidenceClaim:
        """Decode and validate one evidence object.

        Returns:
            A typed claim.

        Raises:
            PolicyError: If enum values or quantitative fields are malformed.

        """
        from .policy_codec import structure_evidence_claim

        return structure_evidence_claim(value)

    def validate_sentence(self, sentence: str) -> None:
        """Enforce the deterministic prose ceiling for this claim.

        Raises:
            PolicyError: If non-causal evidence is phrased as causal impact.

        """
        normalized = sentence.casefold()
        if self.claim_class != ClaimClass.CAUSAL and any(
            phrase in normalized for phrase in _CAUSAL_PHRASES
        ):
            raise PolicyError(
                f"sentence exceeds {self.claim_class.value} claim {self.claim_id}"
            )


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


_OBSERVABLE_FIELDS: dict[str, type[Any] | tuple[type[Any], ...]] = {
    "enemy.heroes": (list, tuple, set),
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
    value: Any = None

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
            if expected not in {(list, tuple, set), (list, tuple, set)}:
                raise PolicyError(f"guard {self.field} is not a collection")
            return
        if not isinstance(self.value, expected):
            raise PolicyError(f"guard {self.field} has an incompatible value")

    def matches(self, state: dict[str, Any]) -> bool:
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
            return isinstance(current, int) and current >= self.value
        if self.operator == GuardOperator.AT_MOST:
            return isinstance(current, int) and current <= self.value
        if self.operator == GuardOperator.CONTAINS:
            return isinstance(current, (list, tuple, set)) and self.value in current
        return False

    def as_dict(self) -> dict[str, Any]:
        from .policy_codec import unstructure_guard

        return unstructure_guard(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> Guard:
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

    def matches(self, state: dict[str, Any]) -> bool:
        """Return whether every observable condition matches.

        Returns:
            Whether all conditions match the current observable state.

        """
        return bool(self.guards) and all(guard.matches(state) for guard in self.guards)

    def as_dict(self) -> dict[str, Any]:
        from .policy_codec import unstructure_branch

        return unstructure_branch(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> Branch:
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
        if self.kind == NodeKind.PURCHASE and self.item_id is None:
            raise PolicyError(f"purchase node {self.node_id} has no item")
        if self.kind == NodeKind.SELL and self.item_id is None:
            raise PolicyError(f"sell node {self.node_id} has no item")
        if self.kind == NodeKind.ABILITY and (
            self.ability_id is None or self.level is None
        ):
            raise PolicyError(f"ability node {self.node_id} is incomplete")
        if self.kind in {NodeKind.CHOICE, NodeKind.OBJECTIVE_GATE}:
            if not self.branches:
                raise PolicyError(f"choice node {self.node_id} has no branches")
        elif self.branches:
            raise PolicyError(f"non-choice node {self.node_id} has branches")
        if self.kind == NodeKind.END and self.next_id is not None:
            raise PolicyError(f"end node {self.node_id} has a successor")
        if self.required_flex_slots not in range(4):
            raise PolicyError("required flex slots must be between zero and three")
        if self.sell_priority is not None and self.sell_priority <= 0:
            raise PolicyError("sell priority must be positive when present")
        if (
            self.earliest_time_s is not None
            and self.latest_time_s is not None
            and self.earliest_time_s > self.latest_time_s
        ):
            raise PolicyError(f"node {self.node_id} has an inverted time window")

    def successors(self) -> tuple[str, ...]:
        """Return every graph successor.

        Returns:
            Direct node IDs reached from this node.

        """
        if self.branches:
            return tuple(branch.next_id for branch in self.branches)
        return (self.next_id,) if self.next_id is not None else ()

    def as_dict(self) -> dict[str, Any]:
        from .policy_codec import unstructure_policy_node

        return unstructure_policy_node(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> PolicyNode:
        """Decode one versioned policy node.

        Returns:
            A typed node for every supported kind.

        Raises:
            PolicyError: If the kind is unknown or fields are malformed.

        """
        from .policy_codec import structure_policy_node

        return structure_policy_node(value)


class AbstentionReason(StrEnum):
    STALE_MECHANICS = "stale_or_incomplete_mechanics"
    INADEQUATE_SUPPORT = "inadequate_support_or_overlap"
    EVIDENCE_CONFLICT = "evidence_conflict"
    ILLEGAL_PATH = "illegal_path"
    UNCLEAR_THREAT = "unclear_threat"
    OUT_OF_DISTRIBUTION = "out_of_distribution_state"
    TELEMETRY_FAILURE = "telemetry_failure"


@dataclass(frozen=True)
class Abstention:
    reason: AbstentionReason
    detail: str
    node_id: str | None = None

    def __post_init__(self) -> None:
        """Require an actionable abstention explanation.

        Raises:
            PolicyError: If no detail is supplied.

        """
        if not self.detail.strip():
            raise PolicyError("abstention detail must not be empty")


def _validate_counter_cards(
    cards: tuple[CounterCard, ...],
    nodes: tuple[PolicyNode, ...],
    claim_ids: list[str],
) -> None:
    item_ids = [card.item_id for card in cards]
    if len(item_ids) != len(set(item_ids)):
        raise PolicyError("counter cards must use distinct items")
    claims = set(claim_ids)
    actions = {
        (node.item_id, node.evidence_ref)
        for node in nodes
        if node.kind == NodeKind.PURCHASE and node.optional
    }
    for card in cards:
        if card.evidence_ref not in claims:
            raise PolicyError(
                f"counter card references missing evidence {card.evidence_ref}"
            )
        if (card.item_id, card.evidence_ref) not in actions:
            raise PolicyError("counter card has no matching optional purchase node")


@dataclass(frozen=True)
class BuildPolicy:
    schema_version: int
    hero_id: int
    variant: str
    invariant_kit_id: str
    strategic_role: str
    snapshot_id: str
    entry: str
    nodes: tuple[PolicyNode, ...]
    evidence: tuple[EvidenceClaim, ...]
    ability_plan: tuple[PolicyNode, ...] = ()
    abstentions: tuple[Abstention, ...] = ()
    counter_cards: tuple[CounterCard, ...] = ()

    def __post_init__(self) -> None:
        """Validate policy-level identity and uniqueness.

        Raises:
            PolicyError: If identity fields or node/claim IDs are invalid.

        """
        if self.schema_version != 1:
            raise PolicyError(f"unsupported policy schema {self.schema_version}")
        if self.hero_id <= 0:
            raise PolicyError("policy hero id must be positive")
        if not all(
            value.strip()
            for value in (
                self.variant,
                self.invariant_kit_id,
                self.strategic_role,
                self.snapshot_id,
                self.entry,
            )
        ):
            raise PolicyError("policy identity fields must not be empty")
        graph_node_ids = [node.node_id for node in self.nodes]
        node_ids = [*graph_node_ids, *(node.node_id for node in self.ability_plan)]
        if len(set(node_ids)) != len(node_ids):
            raise PolicyError("policy node IDs must be unique")
        if any(node.kind != NodeKind.ABILITY for node in self.ability_plan):
            raise PolicyError("ability plan may contain only ability nodes")
        claim_ids = [claim.claim_id for claim in self.evidence]
        if len(set(claim_ids)) != len(claim_ids):
            raise PolicyError("policy evidence IDs must be unique")
        if self.entry not in set(graph_node_ids):
            raise PolicyError("policy entry does not resolve")
        for claim in self.evidence:
            if claim.snapshot_id != self.snapshot_id:
                raise PolicyError(f"claim {claim.claim_id} uses a stale snapshot")
        _validate_counter_cards(self.counter_cards, self.nodes, claim_ids)

    @property
    def policy_id(self) -> str:
        return sha256_json(self.as_dict(include_policy_id=False))

    def as_dict(self, *, include_policy_id: bool = True) -> dict[str, Any]:
        from .policy_codec import unstructure_build_policy

        return unstructure_build_policy(self, include_policy_id=include_policy_id)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> BuildPolicy:
        """Decode a policy sidecar and verify its fingerprint.

        Returns:
            A fully typed policy graph.

        Raises:
            PolicyError: If structure, enums, identity, or fingerprint are invalid.

        """
        from .policy_codec import structure_build_policy

        return structure_build_policy(value)


@dataclass(frozen=True)
class ValidationContext:
    item_graph: ItemGraph
    ability_definitions: dict[int, AbilityDefinition]
    level_info: object
    learned_abilities: set[int] = field(default_factory=set)


@dataclass(frozen=True)
class _PathState:
    inventory: InventoryState = field(default_factory=InventoryState)
    ability_actions: tuple[AbilityAction, ...] = ()
    learned: frozenset[int] = frozenset()
    sell_priorities: tuple[tuple[int, int], ...] = ()


def _validate_choice(node: PolicyNode) -> None:
    defaults = [branch for branch in node.branches if branch.is_default]
    if len(defaults) != 1:
        raise PolicyError(f"choice {node.node_id} must have exactly one default")
    guarded = [branch for branch in node.branches if not branch.is_default]
    signatures = [
        tuple(
            (guard.field, guard.operator, repr(guard.value)) for guard in branch.guards
        )
        for branch in guarded
    ]
    if len(set(signatures)) != len(signatures) and any(
        branch.priority is None for branch in guarded
    ):
        raise PolicyError(
            f"choice {node.node_id} has overlapping guards without precedence"
        )
    priorities = [branch.priority for branch in guarded if branch.priority is not None]
    if len(priorities) != len(set(priorities)):
        raise PolicyError(f"choice {node.node_id} has duplicate priorities")


def _apply_node(
    node: PolicyNode,
    state: _PathState,
    context: ValidationContext,
) -> _PathState:
    inventory = state.inventory
    ability_actions = state.ability_actions
    learned = state.learned
    sell_priorities = state.sell_priorities
    try:
        if node.kind == NodeKind.PURCHASE:
            if node.item_id is None:
                raise PolicyError(f"purchase {node.node_id} has no item")
            if node.imbue_target_ability_id is not None:
                validate_imbue(
                    context.ability_definitions,
                    set(learned),
                    node.imbue_target_ability_id,
                    required_qualifier=node.imbue_qualifier,
                    allow_ultimate=node.allow_ultimate_imbue,
                )
            inventory = purchase_item(
                context.item_graph,
                inventory,
                node.item_id,
                required_flex_slots=node.required_flex_slots,
            )
            if node.sell_priority is not None:
                sell_priorities = (*sell_priorities, (node.item_id, node.sell_priority))
        elif node.kind == NodeKind.SELL:
            if node.item_id is None:
                raise PolicyError(f"sell {node.node_id} has no item")
            inventory = sell_item(context.item_graph, inventory, node.item_id)
        elif node.kind == NodeKind.ABILITY:
            if node.ability_id is None or node.level is None:
                raise PolicyError(f"ability {node.node_id} is incomplete")
            ability_actions = (
                *ability_actions,
                AbilityAction(node.level, node.ability_id),
            )
            validate_ability_timeline(
                context.ability_definitions,
                context.level_info,
                ability_actions,
            )
            learned = frozenset((*learned, node.ability_id))
        elif (
            node.kind == NodeKind.OBJECTIVE_GATE and node.unlocks_flex_slots is not None
        ):
            inventory = replace(
                inventory,
                unlocked_flex_slots=node.unlocks_flex_slots,
            )
    except MechanicsError as error:
        raise PolicyError(f"node {node.node_id}: {error}") from error
    return _PathState(inventory, ability_actions, learned, sell_priorities)


def validate_policy(policy: BuildPolicy, context: ValidationContext) -> None:
    """Prove every reachable branch terminates and satisfies hard gates.

    Raises:
        PolicyError: If references, branching, mechanics, evidence, or reachability fail.

    """
    nodes = {node.node_id: node for node in policy.nodes}
    claims = {claim.claim_id: claim for claim in policy.evidence}
    for node in (*policy.nodes, *policy.ability_plan):
        if node.kind in {NodeKind.CHOICE, NodeKind.OBJECTIVE_GATE}:
            _validate_choice(node)
        if node.evidence_ref is not None and node.evidence_ref not in claims:
            raise PolicyError(
                f"node {node.node_id} references missing evidence {node.evidence_ref}"
            )
        if node.kind in {NodeKind.PURCHASE, NodeKind.SELL, NodeKind.ABILITY} and (
            node.evidence_ref is None
        ):
            raise PolicyError(f"action node {node.node_id} has no evidence")
        if node in policy.nodes:
            for successor in (
                *node.successors(),
                *((node.recalculation_next,) if node.recalculation_next else ()),
            ):
                if successor not in nodes:
                    raise PolicyError(
                        f"node {node.node_id} has missing successor {successor}"
                    )

    if policy.ability_plan:
        ability_actions = tuple(
            AbilityAction(node.level, node.ability_id)
            for node in policy.ability_plan
            if node.level is not None and node.ability_id is not None
        )
        if len(ability_actions) != len(policy.ability_plan):
            raise PolicyError("ability plan contains an incomplete action")
        try:
            validate_ability_timeline(
                context.ability_definitions,
                context.level_info,
                ability_actions,
            )
        except MechanicsError as error:
            raise PolicyError(f"ability plan: {error}") from error

    reached: set[str] = set()
    active: set[str] = set()

    def visit(node_id: str, state: _PathState) -> None:
        if node_id in active:
            raise PolicyError(f"policy contains a reachable cycle at {node_id}")
        active.add(node_id)
        reached.add(node_id)
        node = nodes[node_id]
        next_state = _apply_node(node, state, context)
        successors = node.successors()
        if node.kind == NodeKind.END:
            active.remove(node_id)
            return
        if not successors:
            raise PolicyError(f"reachable node {node_id} does not terminate")
        for successor in successors:
            visit(successor, next_state)
        active.remove(node_id)

    visit(policy.entry, _PathState())
    unreachable = set(nodes) - reached
    if unreachable:
        raise PolicyError(
            "policy contains unreachable nodes: " + ", ".join(sorted(unreachable))
        )


@dataclass(frozen=True)
class EvaluationState:
    observable: dict[str, Any]
    inventory: InventoryState = field(default_factory=InventoryState)
    learned_abilities: frozenset[int] = frozenset()
    clock_s: int = 0


@dataclass(frozen=True)
class PolicyDecision:
    node_id: str | None
    kind: NodeKind | None
    abstention: Abstention | None = None


def next_policy_decision(
    policy: BuildPolicy,
    state: EvaluationState,
) -> PolicyDecision:
    """Recalculate from current ownership/state and return the next relevant action.

    Returns:
        The nearest unfulfilled legal policy node or a structured abstention/end.

    """
    nodes = {node.node_id: node for node in policy.nodes}
    current = policy.entry
    visited: set[str] = set()
    while current not in visited:
        visited.add(current)
        node = nodes[current]
        if node.kind in {NodeKind.CHOICE, NodeKind.OBJECTIVE_GATE}:
            matching = [
                branch for branch in node.branches if branch.matches(state.observable)
            ]
            if len(matching) > 1 and any(
                branch.priority is None for branch in matching
            ):
                return PolicyDecision(
                    None,
                    None,
                    Abstention(
                        AbstentionReason.OUT_OF_DISTRIBUTION,
                        "multiple policy guards matched without runtime precedence",
                        node.node_id,
                    ),
                )
            if matching:
                current = min(
                    matching,
                    key=lambda branch: (
                        branch.priority if branch.priority is not None else 0
                    ),
                ).next_id
            else:
                current = next(
                    branch.next_id for branch in node.branches if branch.is_default
                )
            continue
        if node.kind == NodeKind.PURCHASE and node.item_id in state.inventory.owned:
            if node.next_id is None:
                break
            current = node.next_id
            continue
        if node.kind == NodeKind.ABILITY and node.ability_id in state.learned_abilities:
            if node.next_id is None:
                break
            current = node.next_id
            continue
        if node.latest_time_s is not None and state.clock_s > node.latest_time_s:
            if node.recalculation_next is None:
                return PolicyDecision(
                    None,
                    None,
                    Abstention(
                        AbstentionReason.OUT_OF_DISTRIBUTION,
                        f"missed timing for {node.node_id}; no safe recalculation branch",
                        node.node_id,
                    ),
                )
            current = node.recalculation_next
            continue
        return PolicyDecision(node.node_id, node.kind)
    return PolicyDecision(None, NodeKind.END)


@dataclass(frozen=True)
class CounterCard:
    threat: str
    item_id: int
    comparator_item_id: int
    mechanic_ref: str
    legal_timing: str
    alternative: str
    replacement: str
    execution_mode: str
    failure_condition: str
    evidence_ref: str
    enemy_hero_id: int | None = None

    def __post_init__(self) -> None:
        """Require the complete mechanics-first counter contract.

        Raises:
            PolicyError: If any counter decision field is empty or invalid.

        """
        values = (
            self.threat,
            self.mechanic_ref,
            self.legal_timing,
            self.alternative,
            self.replacement,
            self.execution_mode,
            self.failure_condition,
            self.evidence_ref,
        )
        if (
            self.item_id <= 0
            or self.comparator_item_id <= 0
            or self.comparator_item_id == self.item_id
            or not all(value.strip() for value in values)
        ):
            raise PolicyError(
                "counter card is missing a mechanics-first contract field"
            )
        if self.enemy_hero_id is not None and self.enemy_hero_id <= 0:
            raise PolicyError("counter card enemy hero id must be positive")

    def as_dict(self) -> dict[str, Any]:
        """Return the complete serializable decision contract.

        Returns:
            A JSON-compatible counter-card object.

        """
        from .policy_codec import unstructure_counter_card

        return unstructure_counter_card(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> CounterCard:
        """Decode a complete counter card.

        Returns:
            The validated counter card.

        Raises:
            PolicyError: If the object is incomplete or malformed.

        """
        from .policy_codec import structure_counter_card

        return structure_counter_card(value)


@dataclass(frozen=True)
class SpikeCard:
    name: str
    prerequisites: tuple[str, ...]
    acquisition_state: str
    mechanical_delta: str
    conversion_window: str
    failure_conditions: tuple[str, ...]
    counterplay: tuple[str, ...]
    evidence_class: ClaimClass
    confidence: float
    evidence_ref: str

    def __post_init__(self) -> None:
        """Require a state transition rather than an outcome-only peak.

        Raises:
            PolicyError: If transition evidence or confidence is missing.

        """
        if not 0 <= self.confidence <= 1:
            raise PolicyError("spike confidence must be between zero and one")
        if self.evidence_class == ClaimClass.DESCRIPTIVE and not self.mechanical_delta:
            raise PolicyError("an outcome-only maximum cannot define a power spike")
        if not (
            self.name.strip()
            and self.prerequisites
            and self.acquisition_state.strip()
            and self.mechanical_delta.strip()
            and self.conversion_window.strip()
            and self.failure_conditions
            and self.counterplay
            and self.evidence_ref.strip()
        ):
            raise PolicyError("spike card is missing a state-transition field")
