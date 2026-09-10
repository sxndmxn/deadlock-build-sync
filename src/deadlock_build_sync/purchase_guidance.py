"""Assemble full build guidance from the normal admitted evidence path."""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from typing import TYPE_CHECKING

from .mechanics import ItemGraph, MechanicsError
from .purchase_categories import build_purchase_categories
from .purchase_decisions import build_checkpoint_decisions
from .purchase_guidance_types import PurchaseChoice, PurchaseGuidance
from .purchase_planner import plan_purchases
from .purchase_purposes import classify_item_purpose

if TYPE_CHECKING:
    from .purchase_guidance_types import PurchaseTiming
    from .purchase_types import GuideItem, PurchaseGuide


def _build_purchase_choice(
    item: GuideItem,
    guide: PurchaseGuide,
    graph: ItemGraph,
    assets: dict[int, dict[str, object]],
    timing: PurchaseTiming | None,
) -> PurchaseChoice:
    path = tuple(row.item_id for row in guide.core_purchase_items or guide.core_items)
    core = tuple(row.item_id for row in guide.core_items)
    ancestors = graph.transitive_components(item.item_id)
    upgrades = tuple(value for value in core if value in ancestors)
    position = timing.position if timing else None
    basis = (
        "observed adjacent first-purchase anchors in the training build cohort"
        if position is not None
        else "Timing unknown; adjacent purchase evidence is insufficient"
    )
    minimum = max(
        (path.index(value) + 1 for value in upgrades if value in path), default=0
    )
    if position is not None and position < minimum:
        position = None
        basis = "Timing unknown; observed position precedes a required core item"
    branch = None
    blocked = None
    if position is not None:
        try:
            branch = plan_purchases(graph, path, core, {item.item_id: position})
        except (MechanicsError, ValueError) as error:
            blocked = str(error)
    repeated = (
        tuple(
            value
            for value, count in Counter(step.item_id for step in branch.actions).items()
            if count > 1
        )
        if branch
        else ()
    )
    return PurchaseChoice(
        item.item_id,
        item.name,
        item.tier,
        graph.require(item.item_id).cost,
        classify_item_purpose(assets[item.item_id]),
        position,
        timing,
        basis,
        (*ancestors, item.item_id),
        upgrades,
        branch,
        blocked,
        branch.remaining_cost - guide.core_target_cost if branch else None,
        repeated,
    )


def attach_purchase_guidance(
    guide: PurchaseGuide, assets: list[dict[str, object]]
) -> PurchaseGuide:
    graph = ItemGraph.from_assets(assets)
    by_id = {
        key: asset for asset in assets if isinstance((key := asset.get("id")), int)
    }
    timing = {row.item_id: row for row in guide.purchase_timing}
    core = tuple(item.item_id for item in guide.core_items)
    path = tuple(item.item_id for item in guide.core_purchase_items or guide.core_items)
    default = plan_purchases(graph, path, core, {})
    if (
        tuple(step.item_id for step in default.actions) != path
        or set(default.final_inventory) != set(core)
        or default.remaining_cost != guide.core_target_cost
    ):
        raise MechanicsError("Purchase guidance differs from the admitted default path")
    choices = tuple(
        _build_purchase_choice(item, guide, graph, by_id, timing.get(item.item_id))
        for tier in range(1, 5)
        for item in guide.tiers.get(tier, ())
    )
    decisions = tuple(
        decision
        for index in range(len(path) + 1)
        for decision in build_checkpoint_decisions(index, choices, graph)
    )
    guidance = PurchaseGuidance(
        core,
        default,
        choices,
        decisions,
        {item: node.name for item, node in graph.nodes.items()},
        cohort=guide.cohort.as_dict() if guide.cohort else {},
        evidence=guide.evidence_summary,
        automatic_branches=tuple(
            replace(
                branch,
                default_plan=plan_purchases(
                    graph,
                    branch.substituted_path or path,
                    branch.substituted_core or core,
                    {branch.item_id: branch.after_step},
                ),
            )
            for branch in guide.automatic_branches
        ),
    )
    complete = replace(guide, purchase_guidance=guidance)
    return replace(complete, categories=build_purchase_categories(complete))
