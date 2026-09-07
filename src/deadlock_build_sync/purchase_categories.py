"""Project the canonical purchase guide into Steam rows and optional choices."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .purchase_types import MAX_CATEGORY_DESCRIPTION_BYTES, GuideCategory

if TYPE_CHECKING:
    from .match_choices import AutomaticBranch
    from .purchase_guidance_types import PurchaseChoice, PurchaseGuidance
    from .purchase_types import GuideItem, PurchaseGuide


def split_guidance(text: str) -> tuple[str, ...]:
    """Split text into bounded rows.

    Returns:
        All input text in UTF-8 bounded rows.

    """
    result: list[str] = []
    while text:
        end = 0
        size = 0
        for character in text:
            width = len(character.encode("utf-8"))
            if size + width > MAX_CATEGORY_DESCRIPTION_BYTES:
                break
            end += 1
            size += width
        if end < len(text):
            boundary = text.rfind(" ", 0, end)
            if boundary > 0:
                end = boundary + 1
        result.append(text[:end])
        text = text[end:]
    return tuple(result)


def choice_instruction(guidance: PurchaseGuidance, card: PurchaseChoice) -> str:
    route = " -> ".join(guidance.names[item] for item in card.route)
    if card.after_step is None:
        return f"{card.purpose.trigger}. Timing unknown. Route: {route}. Catalog cost: {card.catalog_cost:,} souls. Select a checkpoint before purchase."
    path = guidance.default_path.actions
    resume = (
        path[card.after_step].name if card.after_step < len(path) else "core complete"
    )
    cost = (
        f"Extra cost: {card.extra_path_cost:,} souls."
        if card.extra_path_cost is not None
        else "Cost unavailable."
    )
    rebuy = ", ".join(guidance.names[item] for item in card.rebought_components)
    return (
        f"{card.purpose.trigger}. After core step {card.after_step}. Route: {route}. "
        f"{cost} Resume: {resume}."
        + (f" Rebuy: {rebuy}." if rebuy else "")
        + (f" Blocked: {card.blocked_reason}." if card.blocked_reason else "")
        + conditional_instruction(guidance, card)
    )


def _choice_rows(
    guidance: PurchaseGuidance, card: PurchaseChoice, item: GuideItem
) -> list[GuideCategory]:
    decision = next(
        (row for row in guidance.decisions if card.item_id in row.options), None
    )
    kind = (
        decision.kind if decision else "UPGRADE" if len(card.route) > 1 else "OPTIONAL"
    )
    instruction = choice_instruction(guidance, card)

    return [
        GuideCategory(
            f"{kind} | {card.name}" + (f" ({index + 1})" if index else ""),
            (item,),
            part,
            optional=True,
        )
        for index, part in enumerate(split_guidance(instruction))
    ]


def purchase_categories(guide: PurchaseGuide) -> tuple[GuideCategory, ...]:
    guidance = guide.purchase_guidance
    if guidance is None:
        raise ValueError("Purchase categories require a canonical guide")
    items = {item.item_id: item for group in guide.tiers.values() for item in group}
    core = guide.core_purchase_items or guide.core_items
    result: list[GuideCategory] = []
    for checkpoint in range(len(core) + 1):
        if checkpoint:
            step = guidance.default_path.actions[checkpoint - 1]
            result.append(
                GuideCategory(
                    f"CORE {checkpoint}",
                    (core[checkpoint - 1],),
                    f"AUTO QUEUE | Buy step {checkpoint}. Cost: {step.incremental_cost:,} souls. Total: {step.cumulative_cost:,} souls.",
                )
            )
        for card in guidance.choices:
            if card.after_step == checkpoint:
                result.extend(_choice_rows(guidance, card, items[card.item_id]))
        result.extend(_conditional_rows(guidance, checkpoint, items))
    for card in guidance.choices:
        if card.after_step is None:
            result.extend(_choice_rows(guidance, card, items[card.item_id]))
    result.extend(_core_alternatives(guide))
    result.extend(_pool_rows(guide))
    queued = tuple(
        item.item_id
        for category in result
        if not category.optional
        for item in category.items
    )
    if queued != tuple(step.item_id for step in guidance.default_path.actions):
        raise ValueError("Steam Queue differs from the canonical component path")
    return tuple(result)


def category_records(categories: tuple[GuideCategory, ...]) -> list[dict[str, object]]:
    return [
        {
            "name": category.name,
            "optional": category.optional,
            "description": category.description,
            "width": category.width,
            "height": category.height,
            "items": [
                {
                    "item_id": item.item_id,
                    "item": item.name,
                    "annotation": item.annotation,
                    "required_flex_slots": item.required_flex_slots,
                    "sell_priority": item.sell_priority,
                    "imbue_target_ability_id": item.imbue_target_ability_id,
                }
                for item in category.items
            ],
        }
        for category in categories
    ]


def _core_alternatives(guide: PurchaseGuide) -> list[GuideCategory]:
    result: list[GuideCategory] = []
    for alternative in guide.core_alternatives:
        item = next(
            value
            for value in guide.optional_core_items
            if value.item_id == alternative.item_id
        )
        instruction = f"{alternative.when} {alternative.swap}. {alternative.why} {alternative.skip}"
        result.extend(
            GuideCategory("OPTIONAL CORE", (item,), part, optional=True)
            for part in split_guidance(instruction)
        )
    return result


def conditional_instruction(guidance: PurchaseGuidance, card: PurchaseChoice) -> str:
    return "".join(
        _branch_instruction(guidance, branch)
        for branch in guidance.automatic_branches
        if branch.item_id == card.item_id
    )


def _branch_instruction(guidance: PurchaseGuidance, branch: AutomaticBranch) -> str:
    condition = (
        f"wealth is {branch.value} (personal net worth / lobby mean; behind <0.90, ahead >1.10)"
        if branch.condition == "relative_wealth"
        else f"enemy hero {branch.value} is present"
        if branch.condition == "enemy_hero"
        else f"enemy owns {guidance.names.get(int(branch.value), str(branch.value))}"
    )
    instruction = f" IF {condition}, choose this item after step {branch.after_step}."
    if branch.substituted_core:
        instruction += f" Replace {guidance.names[branch.comparator_item_id]}; use its separately validated core path."
    return instruction


def _conditional_rows(
    guidance: PurchaseGuidance, checkpoint: int, items: dict[int, GuideItem]
) -> list[GuideCategory]:
    result = []
    cards = {card.item_id: card for card in guidance.choices}
    for branch in guidance.automatic_branches:
        if branch.after_step != checkpoint:
            continue
        card = cards[branch.item_id]
        plan = branch.default_plan
        if plan is None:
            raise ValueError("Automatic branch has no canonical purchase plan")
        route = " -> ".join(guidance.names[item] for item in card.route)
        steps = guidance.default_path.actions
        resume_at = checkpoint + 1 if branch.substituted_core else checkpoint
        resume = steps[resume_at].name if resume_at < len(steps) else "core complete"
        extra = plan.remaining_cost - guidance.default_path.remaining_cost
        instruction = (
            _branch_instruction(guidance, branch)
            + f" Route: {route}. Extra cost: {extra:,} souls. Resume: {resume}."
        )
        result.extend(
            GuideCategory(
                "OPTIONAL | CONDITIONAL", (items[card.item_id],), part, optional=True
            )
            for part in split_guidance(instruction)
        )
    return result


def _pool_rows(guide: PurchaseGuide) -> list[GuideCategory]:
    return [
        GuideCategory(
            f"ITEM POOL | TIER {tier}",
            guide.tiers.get(tier, ()),
            "Optional items. These tiers are not a purchase order."
            if guide.tiers.get(tier)
            else "No supported options are available.",
            optional=True,
        )
        for tier in range(1, 5)
    ]
