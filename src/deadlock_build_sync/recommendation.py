from __future__ import annotations

from .build_evidence import (
    THREAT_CLASSES,
    BuildEvidenceCatalog,
)
from .mechanics import (
    InventoryState,
    ItemGraph,
    MechanicsError,
    classify_observed_item_threats,
    purchase_item,
)
from .policy import (
    BuildPolicy,
    CounterCard,
    EvaluationState,
    NodeKind,
    PolicyNode,
    next_policy_decision,
)
from .recommendation_plan import recommend_guide
from .recommendation_state import (
    DECISION_STATE_SCHEMA_VERSION,
    DecisionState,
    Recommendation,
    RecommendationAction,
    RecommendationError,
)
from .value_validation import integer

__all__ = [
    "DECISION_STATE_SCHEMA_VERSION",
    "DecisionState",
    "Recommendation",
    "RecommendationAction",
    "RecommendationError",
    "recommend",
]


def _validate_evidence_identity(
    catalog: BuildEvidenceCatalog,
    state: DecisionState,
) -> None:
    expected_patch = catalog.patch.get("identity")
    expected_match_mode = catalog.cohort.get("match_mode")
    expected_game_mode = catalog.cohort.get("game_mode")
    if state.build_evidence_id != catalog.artifact_id:
        raise RecommendationError("decision state uses another build-evidence artifact")
    if state.client_version != catalog.client_version:
        raise RecommendationError("decision state uses another client version")
    if state.patch_identity != expected_patch:
        raise RecommendationError("decision state uses another patch")
    if (
        not isinstance(expected_match_mode, str)
        or state.match_mode.casefold() != expected_match_mode.casefold()
    ):
        raise RecommendationError("decision state uses another matchmaking mode")
    if (
        not isinstance(expected_game_mode, str)
        or state.game_mode.casefold() != expected_game_mode.casefold()
    ):
        raise RecommendationError("decision state uses another game mode")
    minimum_badge = catalog.cohort.get("minimum_badge")
    maximum_badge = catalog.cohort.get("maximum_badge")
    hero = catalog.heroes.get(state.hero_id)
    if hero is not None and hero.cohort is not None:
        minimum_badge = hero.cohort.minimum_badge
        maximum_badge = hero.cohort.maximum_badge
    if (
        not isinstance(minimum_badge, int)
        or not isinstance(maximum_badge, int)
        or not minimum_badge <= state.average_badge <= maximum_badge
    ):
        raise RecommendationError("decision state rank is outside the evidence cohort")


def _validate_inventory(state: DecisionState, graph: ItemGraph) -> InventoryState:
    if len(state.owned_items) != len(set(state.owned_items)):
        raise RecommendationError("decision state repeats an owned item")
    inventory = InventoryState(state.owned_items, state.unlocked_flex_slots)
    capacity = 9 + state.unlocked_flex_slots
    active = sum(graph.require(item_id).active for item_id in state.owned_items)
    if state.open_slots != capacity - len(state.owned_items):
        raise RecommendationError("decision state open-slot count is inconsistent")
    if state.active_bindings != active or active > 4:
        raise RecommendationError("decision state active bindings are inconsistent")
    component_ids = {
        component for item_id in graph.nodes for component in graph.components[item_id]
    }
    if set(state.owned_components) != set(state.owned_items) & component_ids:
        raise RecommendationError("decision state component ownership is inconsistent")
    return inventory


def _find_next_component_purchase(
    target_item_id: int,
    inventory: InventoryState,
    graph: ItemGraph,
) -> tuple[int, int] | None:
    def first_missing(item_id: int) -> int | None:
        if item_id in inventory.owned:
            return None
        for component_id in graph.components[graph.require(item_id).item_id]:
            if component_id in inventory.owned:
                continue
            nested = first_missing(component_id)
            return component_id if nested is None else nested
        return item_id

    item_id = first_missing(target_item_id)
    if item_id is None:
        return None
    try:
        purchase_item(graph, inventory, item_id)
    except MechanicsError:
        return None
    return item_id, graph.incremental_cash_cost(item_id, inventory.owned)


def _collect_observed_threats(
    state: DecisionState,
    assets: list[dict[str, object]],
    graph: ItemGraph,
) -> frozenset[str]:
    by_id = {
        integer(asset.get("id")): asset
        for asset in assets
        if isinstance(asset.get("id"), int)
    }
    inferred: set[str] = set()
    for item_id in state.enemy_item_ids:
        graph.require(item_id)
        inferred.update(classify_observed_item_threats(by_id[item_id]))
    if state.active_bindings == 4:
        inferred.add("active_slot_burden")
    return frozenset((*state.threats, *inferred))


def _validate_decision_mechanics(
    state: DecisionState,
    assets: list[dict[str, object]],
) -> tuple[ItemGraph, InventoryState]:
    try:
        graph = ItemGraph.from_assets(assets)
        return graph, _validate_inventory(state, graph)
    except MechanicsError as error:
        raise RecommendationError(str(error)) from error


def _build_evaluation_state(
    state: DecisionState,
    threats: frozenset[str],
    inventory: InventoryState,
) -> EvaluationState:
    observable = {
        "enemy.heroes": state.enemy_hero_ids,
        "enemy.lane_heroes": state.lane_enemy_hero_ids,
        "enemy.threats": tuple(sorted(threats)),
        "enemy.items": state.enemy_item_ids,
        "ally.heroes": state.allied_hero_ids,
        "inventory.items": state.owned_items,
        "inventory.components": state.owned_components,
        "inventory.open_slots": state.open_slots,
        "inventory.active_bindings": state.active_bindings,
        "inventory.flex_slots": state.unlocked_flex_slots,
        "clock_s": state.clock_s,
        "economy.liquid": state.liquid_souls,
        "objectives.available": state.objectives,
        "objectives.flex_slots": state.unlocked_flex_slots,
        "cohort.match_mode": state.match_mode,
        "cohort.rank_badge": state.average_badge,
    }
    return EvaluationState(
        observable,
        inventory=inventory,
        learned_abilities=frozenset(state.learned_abilities),
        clock_s=state.clock_s,
    )


def _is_required_core_complete(policy: BuildPolicy, inventory: InventoryState) -> bool:
    required = {
        node.item_id
        for node in policy.nodes
        if node.kind == NodeKind.PURCHASE and not node.optional
    }
    return bool(required) and required <= set(inventory.owned)


def _find_policy_node(policy: BuildPolicy, node_id: str) -> PolicyNode:
    return next(node for node in policy.nodes if node.node_id == node_id)


def _find_counter_card(policy: BuildPolicy, node: PolicyNode) -> CounterCard | None:
    matches = [
        card
        for card in policy.counter_cards
        if card.item_id == node.item_id and card.evidence_ref == node.evidence_ref
    ]
    if len(matches) > 1:
        raise RecommendationError("policy has ambiguous counter metadata")
    return matches[0] if matches else None


def _recommend_policy_node(
    policy: BuildPolicy,
    state: DecisionState,
    node: PolicyNode,
    inventory: InventoryState,
    graph: ItemGraph,
) -> Recommendation:
    if node.kind != NodeKind.PURCHASE or node.item_id is None:
        return Recommendation(
            RecommendationAction.ABSTAIN,
            state.hero_id,
            policy.policy_id,
            reason=f"policy action {node.kind.value} is not executable by recommend",
        )
    purchase = _find_next_component_purchase(node.item_id, inventory, graph)
    if purchase is None:
        return Recommendation(
            RecommendationAction.ABSTAIN,
            state.hero_id,
            policy.policy_id,
            reason=f"policy purchase {node.node_id} is illegal in the supplied state",
        )
    item_id, cost = purchase
    claim = next(
        (claim for claim in policy.evidence if claim.claim_id == node.evidence_ref),
        None,
    )
    card = _find_counter_card(policy, node)
    support = None
    if claim is not None:
        support = claim.numerator if claim.numerator is not None else claim.support
    support_share = (
        claim.estimate if claim is not None and claim.numerator is not None else None
    )
    action = (
        RecommendationAction.BUY
        if state.liquid_souls >= cost
        else RecommendationAction.SAVE
    )
    return Recommendation(
        action,
        state.hero_id,
        policy.policy_id,
        item_id,
        node.item_id,
        cost,
        support,
        support_share,
        "situational" if node.optional else "policy",
        node.annotation or "Deterministic typed policy graph.",
        card.as_dict() if card is not None else None,
    )


def recommend(
    catalog: BuildEvidenceCatalog,
    policy: BuildPolicy,
    state: DecisionState,
    assets: list[dict[str, object]],
) -> Recommendation:
    """Return the next supported legal action without mutating Steam.

    Returns:
        A buy, save, end, or structured abstention.

    Raises:
        RecommendationError: If state identity or mechanics are malformed.

    """
    _validate_evidence_identity(catalog, state)
    if state.hero_id not in catalog.heroes:
        raise RecommendationError("decision state hero is absent from build evidence")
    if policy.hero_id != state.hero_id:
        raise RecommendationError("decision state hero differs from the build policy")
    graph, inventory = _validate_decision_mechanics(state, assets)
    unknown_threats = sorted(set(state.threats) - THREAT_CLASSES)
    if unknown_threats:
        return Recommendation(
            RecommendationAction.ABSTAIN,
            state.hero_id,
            policy.policy_id,
            reason="unknown threat classes: " + ", ".join(unknown_threats),
        )
    try:
        observed_threats = _collect_observed_threats(state, assets, graph)
    except MechanicsError as error:
        raise RecommendationError(str(error)) from error
    builds = catalog.hero_builds.get(state.hero_id, (catalog.heroes[state.hero_id],))
    evidence = next(
        (build for build in builds if build.path_id == policy.path_id), None
    )
    if (
        evidence is not None
        and evidence.discovery.get("method") == "eclat_leiden_pairwise"
    ):
        return recommend_guide(evidence, policy, state, assets)
    if _is_required_core_complete(policy, inventory):
        return Recommendation(
            RecommendationAction.END,
            state.hero_id,
            policy.policy_id,
            reason="required policy purchases are currently owned",
        )
    decision = next_policy_decision(
        policy,
        _build_evaluation_state(state, observed_threats, inventory),
    )
    if decision.abstention is not None:
        return Recommendation(
            RecommendationAction.ABSTAIN,
            state.hero_id,
            policy.policy_id,
            reason=decision.abstention.detail,
        )
    if decision.kind == NodeKind.END:
        return Recommendation(
            RecommendationAction.END,
            state.hero_id,
            policy.policy_id,
            reason="typed policy graph is complete",
        )
    if decision.node_id is not None:
        return _recommend_policy_node(
            policy,
            state,
            _find_policy_node(policy, decision.node_id),
            inventory,
            graph,
        )
    return Recommendation(
        RecommendationAction.ABSTAIN,
        state.hero_id,
        policy.policy_id,
        reason="typed policy graph produced no executable action",
    )
