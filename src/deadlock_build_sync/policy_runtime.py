from __future__ import annotations

from dataclasses import dataclass, field, replace

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
from .policy_claims import EvidenceClaim, PolicyError
from .policy_graph import (
    NodeKind,
    PolicyNode,
)
from .policy_model import Abstention, AbstentionReason, BuildPolicy


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


def _apply_purchase_node(
    node: PolicyNode,
    state: _PathState,
    context: ValidationContext,
) -> _PathState:
    if node.item_id is None:
        raise PolicyError(f"purchase {node.node_id} has no item")
    if node.imbue_target_ability_id is not None:
        validate_imbue(
            context.ability_definitions,
            set(state.learned),
            node.imbue_target_ability_id,
            required_qualifier=node.imbue_qualifier,
            allow_ultimate=node.allow_ultimate_imbue,
        )
    inventory = purchase_item(
        context.item_graph,
        state.inventory,
        node.item_id,
        required_flex_slots=node.required_flex_slots,
    )
    sell_priorities = state.sell_priorities
    if node.sell_priority is not None:
        sell_priorities = (*sell_priorities, (node.item_id, node.sell_priority))
    return _PathState(
        inventory,
        state.ability_actions,
        state.learned,
        sell_priorities,
    )


def _apply_sell_node(
    node: PolicyNode,
    state: _PathState,
    context: ValidationContext,
) -> _PathState:
    if node.item_id is None:
        raise PolicyError(f"sell {node.node_id} has no item")
    inventory = sell_item(context.item_graph, state.inventory, node.item_id)
    return _PathState(
        inventory,
        state.ability_actions,
        state.learned,
        state.sell_priorities,
    )


def _apply_ability_node(
    node: PolicyNode,
    state: _PathState,
    context: ValidationContext,
) -> _PathState:
    if node.ability_id is None or node.level is None:
        raise PolicyError(f"ability {node.node_id} is incomplete")
    ability_actions = (
        *state.ability_actions,
        AbilityAction(node.level, node.ability_id),
    )
    validate_ability_timeline(
        context.ability_definitions,
        context.level_info,
        ability_actions,
    )
    learned = frozenset((*state.learned, node.ability_id))
    return _PathState(state.inventory, ability_actions, learned, state.sell_priorities)


def _apply_node(
    node: PolicyNode,
    state: _PathState,
    context: ValidationContext,
) -> _PathState:
    try:
        if node.kind == NodeKind.PURCHASE:
            return _apply_purchase_node(node, state, context)
        if node.kind == NodeKind.SELL:
            return _apply_sell_node(node, state, context)
        if node.kind == NodeKind.ABILITY:
            return _apply_ability_node(node, state, context)
        if node.kind == NodeKind.OBJECTIVE_GATE and node.unlocks_flex_slots is not None:
            inventory = replace(
                state.inventory,
                unlocked_flex_slots=node.unlocks_flex_slots,
            )
            return _PathState(
                inventory,
                state.ability_actions,
                state.learned,
                state.sell_priorities,
            )
    except MechanicsError as error:
        raise PolicyError(f"node {node.node_id}: {error}") from error
    return state


def _validate_policy_node(
    node: PolicyNode,
    nodes: dict[str, PolicyNode],
    claims: dict[str, EvidenceClaim],
    *,
    validate_successors: bool,
) -> None:
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
    if not validate_successors:
        return
    successors = (
        *node.successors(),
        *((node.recalculation_next,) if node.recalculation_next else ()),
    )
    for successor in successors:
        if successor not in nodes:
            raise PolicyError(f"node {node.node_id} has missing successor {successor}")


def _validate_ability_plan(
    policy: BuildPolicy,
    context: ValidationContext,
) -> None:
    if not policy.ability_plan:
        return
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


class _PolicyGraphValidator:
    def __init__(
        self,
        nodes: dict[str, PolicyNode],
        context: ValidationContext,
    ) -> None:
        self.nodes = nodes
        self.context = context
        self.reached: set[str] = set()
        self.active: set[str] = set()

    def visit(self, node_id: str, state: _PathState) -> None:
        if node_id in self.active:
            raise PolicyError(f"policy contains a reachable cycle at {node_id}")
        self.active.add(node_id)
        self.reached.add(node_id)
        node = self.nodes[node_id]
        next_state = _apply_node(node, state, self.context)
        successors = node.successors()
        if node.kind == NodeKind.END:
            self.active.remove(node_id)
            return
        if not successors:
            raise PolicyError(f"reachable node {node_id} does not terminate")
        for successor in successors:
            self.visit(successor, next_state)
        self.active.remove(node_id)


def validate_policy(policy: BuildPolicy, context: ValidationContext) -> None:
    """Prove every reachable branch terminates and satisfies hard gates.

    Raises:
        PolicyError: If references, branching, mechanics, evidence, or reachability fail.

    """
    nodes = {node.node_id: node for node in policy.nodes}
    claims = {claim.claim_id: claim for claim in policy.evidence}
    for node in policy.nodes:
        _validate_policy_node(node, nodes, claims, validate_successors=True)
    for node in policy.ability_plan:
        _validate_policy_node(node, nodes, claims, validate_successors=False)
    _validate_ability_plan(policy, context)

    graph = _PolicyGraphValidator(nodes, context)
    graph.visit(policy.entry, _PathState())
    unreachable = set(nodes) - graph.reached
    if unreachable:
        raise PolicyError(
            "policy contains unreachable nodes: " + ", ".join(sorted(unreachable))
        )


@dataclass(frozen=True)
class EvaluationState:
    observable: dict[str, object]
    inventory: InventoryState = field(default_factory=InventoryState)
    learned_abilities: frozenset[int] = frozenset()
    clock_s: int = 0


@dataclass(frozen=True)
class PolicyDecision:
    node_id: str | None
    kind: NodeKind | None
    abstention: Abstention | None = None


def _choice_step(
    node: PolicyNode,
    state: EvaluationState,
    nodes: dict[str, PolicyNode],
) -> str | PolicyDecision:
    fulfilled_alternatives = [
        nodes[branch.next_id]
        for branch in node.branches
        if not branch.is_default
        and nodes[branch.next_id].kind == NodeKind.PURCHASE
        and nodes[branch.next_id].optional
        and _node_is_fulfilled(nodes[branch.next_id], state)
    ]
    if len(fulfilled_alternatives) > 1:
        return PolicyDecision(
            None,
            None,
            Abstention(
                AbstentionReason.OUT_OF_DISTRIBUTION,
                "multiple policy alternatives are already owned",
                node.node_id,
            ),
        )
    if fulfilled_alternatives:
        fulfilled = fulfilled_alternatives[0]
        if fulfilled.next_id is None:
            return PolicyDecision(None, NodeKind.END)
        return fulfilled.next_id
    matching = [branch for branch in node.branches if branch.matches(state.observable)]
    if len(matching) > 1 and any(branch.priority is None for branch in matching):
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
        return min(
            matching,
            key=lambda branch: branch.priority if branch.priority is not None else 0,
        ).next_id
    return next(branch.next_id for branch in node.branches if branch.is_default)


def _node_is_fulfilled(node: PolicyNode, state: EvaluationState) -> bool:
    if node.kind == NodeKind.PURCHASE:
        return node.item_id in state.inventory.owned
    if node.kind == NodeKind.ABILITY:
        return node.ability_id in state.learned_abilities
    return False


def _missed_timing_decision(node: PolicyNode) -> PolicyDecision:
    return PolicyDecision(
        None,
        None,
        Abstention(
            AbstentionReason.OUT_OF_DISTRIBUTION,
            f"missed timing for {node.node_id}; no safe recalculation branch",
            node.node_id,
        ),
    )


def _evaluate_policy_node(
    node: PolicyNode,
    state: EvaluationState,
    nodes: dict[str, PolicyNode],
) -> str | PolicyDecision:
    if node.kind in {NodeKind.CHOICE, NodeKind.OBJECTIVE_GATE}:
        return _choice_step(node, state, nodes)
    if _node_is_fulfilled(node, state):
        if node.next_id is None:
            return PolicyDecision(None, NodeKind.END)
        return node.next_id
    if node.latest_time_s is not None and state.clock_s > node.latest_time_s:
        if node.recalculation_next is None:
            return _missed_timing_decision(node)
        return node.recalculation_next
    return PolicyDecision(node.node_id, node.kind)


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
        step = _evaluate_policy_node(node, state, nodes)
        if isinstance(step, PolicyDecision):
            return step
        current = step
    return PolicyDecision(None, NodeKind.END)
