"""Recalculate every pool choice from inventory and combined player choices."""

from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING

from .mechanics import MechanicsError
from .purchase_categories import format_choice_instruction
from .purchase_planner import plan_purchases

if TYPE_CHECKING:
    from .mechanics import ItemGraph
    from .purchase_branching import SelectedPurchaseRoute
    from .purchase_guidance_types import PurchaseGuidance, PurchasePlan, PurchaseState


def evaluate_available_choices(
    guidance: PurchaseGuidance,
    route: SelectedPurchaseRoute,
    state: PurchaseState,
    graph: ItemGraph,
    baseline: PurchasePlan,
) -> list[dict[str, object]]:
    result = []
    for card in guidance.choices:
        current: dict[str, object] = {
            **asdict(card),
            "instruction": format_choice_instruction(guidance, card),
            "current_plan": None,
            "current_blocked_reason": None,
            "extra_remaining_cost": None,
        }
        position = route.positions.get(card.item_id, card.after_step)
        if position is not None:
            try:
                plan = plan_purchases(
                    graph,
                    route.path,
                    route.core,
                    {**route.positions, card.item_id: position},
                    state=state,
                )
                current["current_plan"] = asdict(plan)
                current["extra_remaining_cost"] = (
                    plan.remaining_cost - baseline.remaining_cost
                )
            except (MechanicsError, ValueError) as error:
                current["current_blocked_reason"] = str(error)
        result.append(current)
    return result
