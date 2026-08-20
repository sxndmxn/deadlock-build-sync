from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

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

if TYPE_CHECKING:
    from pathlib import Path

DECISION_STATE_SCHEMA_VERSION = 1
_DECISION_STATE_FIELDS = frozenset({
    "schema_version",
    "build_evidence_id",
    "client_version",
    "patch_identity",
    "match_mode",
    "game_mode",
    "hero_id",
    "clock_s",
    "average_badge",
    "liquid_souls",
    "purchases",
    "inventory",
    "learned_abilities",
    "enemy_hero_ids",
    "enemy_item_ids",
    "allied_hero_ids",
    "objectives",
    "threats",
})
_INVENTORY_FIELDS = frozenset({
    "items",
    "components",
    "open_slots",
    "flex_slots",
    "active_bindings",
})


class RecommendationError(ValueError):
    """Raised when decision state or recommendation evidence is invalid."""


class RecommendationAction(StrEnum):
    BUY = "buy"
    SAVE = "save"
    END = "end"
    ABSTAIN = "abstain"


@dataclass(frozen=True)
class DecisionState:
    build_evidence_id: str
    client_version: int
    patch_identity: str
    match_mode: str
    game_mode: str
    hero_id: int
    clock_s: int
    average_badge: int
    liquid_souls: int
    purchases: tuple[int, ...]
    owned_items: tuple[int, ...]
    owned_components: tuple[int, ...]
    open_slots: int
    unlocked_flex_slots: int
    active_bindings: int
    learned_abilities: tuple[int, ...]
    enemy_hero_ids: tuple[int, ...] = ()
    enemy_item_ids: tuple[int, ...] = ()
    allied_hero_ids: tuple[int, ...] = ()
    objectives: tuple[str, ...] = ()
    threats: tuple[str, ...] = ()

    @classmethod
    def from_file(cls, path: Path) -> DecisionState:
        """Load and validate a deidentified decision-state JSON document.

        Returns:
            The closed recommendation state.

        Raises:
            RecommendationError: If the document is missing or malformed.

        """
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise RecommendationError(
                f"could not read decision state {path}: {error}"
            ) from error
        if not isinstance(value, dict):
            raise RecommendationError("decision state root must be an object")
        if value.get("schema_version") != DECISION_STATE_SCHEMA_VERSION:
            raise RecommendationError("unsupported decision-state schema")
        unknown = set(value) - _DECISION_STATE_FIELDS
        if unknown:
            raise RecommendationError(
                "decision state contains unsupported fields: "
                + ", ".join(sorted(str(field) for field in unknown))
            )
        inventory = value.get("inventory")
        if not isinstance(inventory, dict):
            raise RecommendationError("decision state has no inventory")
        unknown_inventory = set(inventory) - _INVENTORY_FIELDS
        if unknown_inventory:
            raise RecommendationError(
                "decision state inventory contains unsupported fields: "
                + ", ".join(sorted(str(field) for field in unknown_inventory))
            )
        return cls(
            build_evidence_id=_text(
                value.get("build_evidence_id"), "build evidence id"
            ),
            client_version=_integer(
                value.get("client_version"), "client version", minimum=1
            ),
            patch_identity=_text(value.get("patch_identity"), "patch identity"),
            match_mode=_text(value.get("match_mode"), "match mode"),
            game_mode=_text(value.get("game_mode"), "game mode"),
            hero_id=_integer(value.get("hero_id"), "hero id", minimum=1),
            clock_s=_integer(value.get("clock_s"), "clock", minimum=0),
            average_badge=_integer(
                value.get("average_badge"), "average badge", minimum=1
            ),
            liquid_souls=_integer(value.get("liquid_souls"), "liquid souls", minimum=0),
            purchases=_integers(value.get("purchases"), "purchase history"),
            owned_items=_unique_integers(inventory.get("items"), "owned items"),
            owned_components=_unique_integers(
                inventory.get("components"), "owned components"
            ),
            open_slots=_integer(inventory.get("open_slots"), "open slots", minimum=0),
            unlocked_flex_slots=_integer(
                inventory.get("flex_slots"), "flex slots", minimum=0
            ),
            active_bindings=_integer(
                inventory.get("active_bindings"), "active bindings", minimum=0
            ),
            learned_abilities=_unique_integers(
                value.get("learned_abilities"), "learned abilities"
            ),
            enemy_hero_ids=_unique_integers(
                value.get("enemy_hero_ids", []), "enemy heroes"
            ),
            enemy_item_ids=_unique_integers(
                value.get("enemy_item_ids", []), "enemy items"
            ),
            allied_hero_ids=_unique_integers(
                value.get("allied_hero_ids", []), "allied heroes"
            ),
            objectives=_unique_strings(value.get("objectives", []), "objectives"),
            threats=_unique_strings(value.get("threats", []), "threats"),
        )


@dataclass(frozen=True)
class Recommendation:
    action: RecommendationAction
    hero_id: int
    policy_id: str
    item_id: int | None = None
    target_item_id: int | None = None
    incremental_cost: int | None = None
    support: int | None = None
    support_share: float | None = None
    backoff_level: str | None = None
    reason: str = ""
    counter: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action.value,
            "hero_id": self.hero_id,
            "policy_id": self.policy_id,
            "item_id": self.item_id,
            "target_item_id": self.target_item_id,
            "incremental_cost": self.incremental_cost,
            "support": self.support,
            "support_share": self.support_share,
            "backoff_level": self.backoff_level,
            "reason": self.reason,
            "counter": self.counter,
        }


def _integer(value: object, label: str, *, minimum: int = 1) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise RecommendationError(f"decision state has invalid {label}")
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RecommendationError(f"decision state has invalid {label}")
    return value.strip()


def _integers(value: object, label: str) -> tuple[int, ...]:
    if not isinstance(value, list):
        raise RecommendationError(f"decision state has invalid {label}")
    return tuple(_integer(item, label) for item in value)


def _unique_integers(value: object, label: str) -> tuple[int, ...]:
    result = _integers(value, label)
    if len(result) != len(set(result)):
        raise RecommendationError(f"decision state has duplicate {label}")
    return result


def _unique_strings(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise RecommendationError(f"decision state has invalid {label}")
    result = tuple(str(item).strip() for item in value)
    if len(result) != len(set(result)):
        raise RecommendationError(f"decision state has duplicate {label}")
    return result


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


def _next_purchase(
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


def _observed_threats(
    state: DecisionState,
    assets: list[dict[str, Any]],
    graph: ItemGraph,
) -> frozenset[str]:
    by_id = {
        int(asset["id"]): asset for asset in assets if isinstance(asset.get("id"), int)
    }
    inferred: set[str] = set()
    for item_id in state.enemy_item_ids:
        graph.require(item_id)
        inferred.update(classify_observed_item_threats(by_id[item_id]))
    if state.active_bindings == 4:
        inferred.add("active_slot_burden")
    return frozenset((*state.threats, *inferred))


def _decision_mechanics(
    state: DecisionState,
    assets: list[dict[str, Any]],
) -> tuple[ItemGraph, InventoryState]:
    try:
        graph = ItemGraph.from_assets(assets)
        return graph, _validate_inventory(state, graph)
    except MechanicsError as error:
        raise RecommendationError(str(error)) from error


def _evaluation_state(
    state: DecisionState,
    threats: frozenset[str],
    inventory: InventoryState,
) -> EvaluationState:
    observable = {
        "enemy.heroes": state.enemy_hero_ids,
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


def _required_core_complete(policy: BuildPolicy, inventory: InventoryState) -> bool:
    required = {
        node.item_id
        for node in policy.nodes
        if node.kind == NodeKind.PURCHASE and not node.optional
    }
    return bool(required) and required <= set(inventory.owned)


def _policy_node(policy: BuildPolicy, node_id: str) -> PolicyNode:
    return next(node for node in policy.nodes if node.node_id == node_id)


def _counter_card(policy: BuildPolicy, node: PolicyNode) -> CounterCard | None:
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
    purchase = _next_purchase(node.item_id, inventory, graph)
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
    card = _counter_card(policy, node)
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
    assets: list[dict[str, Any]],
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
    graph, inventory = _decision_mechanics(state, assets)
    unknown_threats = sorted(set(state.threats) - THREAT_CLASSES)
    if unknown_threats:
        return Recommendation(
            RecommendationAction.ABSTAIN,
            state.hero_id,
            policy.policy_id,
            reason="unknown threat classes: " + ", ".join(unknown_threats),
        )
    try:
        observed_threats = _observed_threats(state, assets, graph)
    except MechanicsError as error:
        raise RecommendationError(str(error)) from error
    if _required_core_complete(policy, inventory):
        return Recommendation(
            RecommendationAction.END,
            state.hero_id,
            policy.policy_id,
            reason="required policy purchases are currently owned",
        )
    decision = next_policy_decision(
        policy,
        _evaluation_state(state, observed_threats, inventory),
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
            _policy_node(policy, decision.node_id),
            inventory,
            graph,
        )
    return Recommendation(
        RecommendationAction.ABSTAIN,
        state.hero_id,
        policy.policy_id,
        reason="typed policy graph produced no executable action",
    )
