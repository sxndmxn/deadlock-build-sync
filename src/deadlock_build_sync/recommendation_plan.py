"""Recalculate the selected identity with the same guide used for Steam."""

from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING

from .build_evidence import select_hero_build
from .mechanics import ItemGraph, MechanicsError
from .purchase_availability import evaluate_available_choices
from .purchase_branching import select_purchase_route
from .purchase_guidance import attach_purchase_guidance
from .purchase_guidance_types import PurchaseState
from .purchase_guide import build_purchase_guide_from_evidence
from .purchase_planner import plan_purchases
from .recommendation_state import (
    Recommendation,
    RecommendationAction,
    RecommendationError,
)
from .value_validation import object_rows

if TYPE_CHECKING:
    from .build_evidence import HeroBuildEvidence
    from .policy import BuildPolicy
    from .purchase_guidance_types import PurchaseGuidance
    from .recommendation_state import DecisionState


def resolve_selected_purchase_positions(
    guidance: PurchaseGuidance, state: DecisionState
) -> dict[int, int]:
    cards = {card.item_id: card for card in guidance.choices}
    positions = {}
    if not set(state.placement_overrides) <= set(state.selected_optional_items):
        raise RecommendationError("Placement overrides must refer to selected items")
    for item in state.selected_optional_items:
        if item not in cards:
            raise RecommendationError(
                "Selected item is outside this identity's item pool"
            )
        position = state.placement_overrides.get(item, cards[item].after_step)
        if position is None:
            raise RecommendationError(
                f"Timing unknown for {cards[item].name}; supply placement_overrides"
            )
        positions[item] = position
    return positions


def recommend_guide(
    evidence: HeroBuildEvidence,
    policy: BuildPolicy,
    state: DecisionState,
    assets: list[dict[str, object]],
) -> Recommendation:
    if (
        state.path_id is not None and state.path_id != evidence.path_id
    ) or policy.path_id != evidence.path_id:
        raise RecommendationError(
            "Decision state and policy use different build identities"
        )
    selected = select_hero_build(evidence, assets)
    guide = attach_purchase_guidance(
        build_purchase_guide_from_evidence(
            {"id": evidence.hero_id, "name": evidence.hero},
            selected,
        ),
        assets,
    )
    guidance = guide.purchase_guidance
    if guidance is None:
        raise RecommendationError("Build has no canonical purchase guide")
    graph = ItemGraph.from_assets(assets)
    positions = resolve_selected_purchase_positions(guidance, state)
    route = select_purchase_route(guidance, state, graph, positions)
    current = PurchaseState(
        state.owned_items, state.liquid_souls, state.unlocked_flex_slots
    )
    try:
        plan = plan_purchases(
            graph, route.path, route.core, route.positions, state=current
        )
    except (MechanicsError, ValueError) as error:
        raise RecommendationError(str(error)) from error
    first = plan.actions[0] if plan.actions else None
    action = (
        RecommendationAction.END
        if first is None
        else RecommendationAction.SAVE
        if plan.save_souls
        else RecommendationAction.BUY
    )
    return Recommendation(
        action,
        state.hero_id,
        policy.policy_id,
        item_id=first.item_id if first else None,
        target_item_id=first.item_id if first else None,
        incremental_cost=first.incremental_cost if first else 0,
        reason=route.source,
        purchase_plan={
            "schema_version": 2,
            "core": list(route.core),
            "applied_branch": asdict(route.branch) if route.branch else None,
            "path_id": evidence.path_id,
            "next_purchase": asdict(first) if first else None,
            "cash_shortfall": plan.save_souls,
            "remaining_route": [asdict(step) for step in plan.actions],
            "remaining_cost": plan.remaining_cost,
            "final_inventory": list(plan.final_inventory),
            "selected_placements": {
                str(item): index for item, index in route.positions.items()
            },
            "available_choices": evaluate_available_choices(
                guidance, route, current, graph, plan
            ),
            "relative_wealth": state.economy.relative_wealth(state.clock_s)
            if state.economy
            else None,
        },
    )


def render_recommendation_markdown(decision: Recommendation) -> str:
    details = decision.purchase_plan or {}
    lines = [
        f"# {decision.action.value.upper()}",
        "",
        decision.reason,
        "",
        f"Build: {details.get('path_id', decision.policy_id)}.",
        f"Cash shortfall: {details.get('cash_shortfall', 0) or 0} souls.",
        f"Remaining cost: {details.get('remaining_cost', 0)} souls.",
        "",
    ]
    for index, step in enumerate(
        object_rows(details.get("remaining_route")) or [], start=1
    ):
        lines.append(f"{index}. {step['name']}: {step['incremental_cost']} souls.")
    choices = object_rows(details.get("available_choices"))
    if choices is not None:
        lines.extend(["", "## Available choices", ""])
        lines.extend(
            f"- {choice['name']}: {choice['instruction']}"
            + (
                f" Extra remaining cost: {choice['extra_remaining_cost']} souls."
                if choice.get("extra_remaining_cost") is not None
                else ""
            )
            + (
                f" Blocked: {choice['current_blocked_reason']}."
                if choice.get("current_blocked_reason")
                else ""
            )
            for choice in choices
        )
    return "\n".join(lines) + "\n"
