"""Explicit choices precede admitted conditions and the default core route."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .mechanics import MechanicsError
from .purchase_guidance_types import PurchaseState
from .purchase_planner import (
    find_first_incomplete_checkpoint,
    is_item_or_upgrade_owned,
    plan_purchases,
)
from .recommendation_state import RecommendationError

if TYPE_CHECKING:
    from .match_choices import AutomaticBranch
    from .mechanics import ItemGraph
    from .purchase_guidance_types import PurchaseGuidance
    from .recommendation_state import DecisionState


@dataclass(frozen=True)
class SelectedPurchaseRoute:
    path: tuple[int, ...]
    core: tuple[int, ...]
    positions: dict[int, int]
    source: str
    branch: AutomaticBranch | None = None


def select_purchase_route(
    guidance: PurchaseGuidance,
    state: DecisionState,
    graph: ItemGraph,
    positions: dict[int, int],
) -> SelectedPurchaseRoute:
    path = tuple(step.item_id for step in guidance.default_path.actions)
    branches = sorted(
        guidance.automatic_branches,
        key=lambda row: (-row.lower_bound, -row.support, row.item_id),
    )
    if state.core_substitution_item_id is not None:
        candidates = [
            row
            for row in branches
            if row.item_id == state.core_substitution_item_id and row.substituted_core
        ]
        if not candidates or state.core_substitution_item_id not in positions:
            raise RecommendationError(
                "Selected core substitution lacks admitted branch evidence or an explicit item selection"
            )
        branch = candidates[0]
        return SelectedPurchaseRoute(
            branch.substituted_path,
            branch.substituted_core,
            positions,
            "explicit core substitution",
            branch,
        )
    if positions:
        return SelectedPurchaseRoute(
            path, guidance.core_ids, positions, "explicit selection"
        )
    checkpoint = find_first_incomplete_checkpoint(graph, path, state.owned_items)
    for branch in branches:
        if (
            branch.after_step != checkpoint
            or not branch.matches(state)
            or is_item_or_upgrade_owned(graph, branch.item_id, state.owned_items)
        ):
            continue
        route = SelectedPurchaseRoute(
            branch.substituted_path or path,
            branch.substituted_core or guidance.core_ids,
            {branch.item_id: branch.after_step},
            "admitted matching branch",
            branch,
        )
        try:
            plan_purchases(
                graph,
                route.path,
                route.core,
                route.positions,
                state=PurchaseState(
                    state.owned_items, state.liquid_souls, state.unlocked_flex_slots
                ),
            )
        except (MechanicsError, ValueError):
            continue
        return route
    return SelectedPurchaseRoute(path, guidance.core_ids, {}, "default path")
