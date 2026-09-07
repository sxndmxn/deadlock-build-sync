"""Phone-readable build guides with interleaved choices and the whole item pool."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .guide_groups import VARIANT_RULE, variant_changes
from .purchase_categories import choice_instruction, conditional_instruction

if TYPE_CHECKING:
    from .purchase_guidance_types import (
        PurchaseChoice,
        PurchaseDecision,
        PurchaseGuidance,
    )
    from .purchase_types import PurchaseGuide


def _route(guidance: PurchaseGuidance, items: tuple[int, ...]) -> str:
    return " → ".join(guidance.names[item] for item in items)


def _option(guidance: PurchaseGuidance, card: PurchaseChoice) -> str:
    path = guidance.default_path.actions
    next_item = (
        path[card.after_step].name
        if card.after_step is not None and card.after_step < len(path)
        else None
    )
    title = ("UPGRADE " if len(card.route) > 1 else "") + _route(guidance, card.route)
    line = f"- **{title}** — +{card.extra_path_cost:,} souls; " + (
        f"then {next_item}." if next_item else "after the core."
    )
    if card.rebought_components:
        line += " Includes another " + _route(guidance, card.rebought_components) + "."
    stages = [
        row
        for row in guidance.choices
        if row.item_id in card.route[:-1]
        and row.after_step == card.after_step
        and row.extra_path_cost is not None
    ]
    if stages:
        line += (
            " You can stop at "
            + ", ".join(
                f"{row.name} (+{row.extra_path_cost:,} total)" for row in stages
            )
            + "."
        )
    return (
        line
        + " "
        + card.purpose.trigger
        + "."
        + conditional_instruction(guidance, card)
    )


def _decision(guidance: PurchaseGuidance, decision: PurchaseDecision) -> list[str]:
    cards = {card.item_id: card for card in guidance.choices}
    label = decision.kind + (" UPGRADE" if decision.upgrade_fork else "")
    return [
        f"**{label} — {decision.purpose}**",
        "",
        *(_option(guidance, cards[item]) for item in decision.options),
        "",
    ]


def _unplaced(guidance: PurchaseGuidance) -> list[str]:
    lines: list[str] = []
    for card in guidance.choices:
        if card.after_step is None:
            support = (
                f"{card.timing.support}/{card.timing.buyers} buyers"
                if card.timing
                else "No adjacent purchase counts"
            )
            lines.append(
                f"- **{card.name}** — Timing unknown. {card.purpose.label}; {card.catalog_cost:,} souls. {support}. {card.purpose.trigger}."
            )
        elif card.blocked_reason:
            lines.append(f"- **{card.name}** — Blocked: {card.blocked_reason}.")
    return ["## Timing unknown or purchase blocked", "", *lines, ""] if lines else []


def _details(guidance: PurchaseGuidance) -> list[str]:
    lines = ["## Choice details", ""]
    for card in guidance.choices:
        lines.extend([
            f"### {card.name}",
            "",
            choice_instruction(guidance, card),
            f"Timing: {card.timing_basis}.",
            f"Mechanic source: {card.purpose.basis}; {card.purpose.evidence or 'unclassified'}.",
        ])
        if card.plan:
            if card.upgrades_core:
                lines.append(
                    "UPGRADE CORE: "
                    + _route(guidance, card.upgrades_core)
                    + " → "
                    + card.name
                    + "."
                )
            lines.extend([
                "Path: "
                + _route(guidance, tuple(step.item_id for step in card.plan.actions))
                + ".",
                "Ending inventory: "
                + _route(guidance, card.plan.final_inventory)
                + ".",
                f"Extra path cost: {card.extra_path_cost:,} souls.",
            ])
        lines.append("")
    return lines


def build_markdown(guide: PurchaseGuide, *, details: bool = False) -> str:
    """Render the exact admitted guide without a separate research runtime.

    Returns:
        A complete Markdown build.

    Raises:
        ValueError: If purchase guidance was not generated.

    """
    guidance = guide.purchase_guidance
    if guidance is None:
        raise ValueError("Build has no purchase guidance; generate it with build")
    if not details and any(category.compact for category in guide.rendered_categories):
        return _compact_markdown(guide, guidance)
    lines = [
        f"# {guide.hero_name} — {guide.build_archetype}",
        "",
        f"Build: `{guide.path_id}`. Core: {guidance.default_path.remaining_cost:,} souls.",
        f"Ranks: {guide.rank_identity}. Evidence: {guidance.evidence.get('status', 'observed')}. Timing: {guidance.evidence.get('timing_status', 'uncertain')}. Limits: {guidance.evidence.get('limitations', [])}.",
        "",
        "Follow the core unless you need an optional effect. PICK ONE means the next purchase for that need. You can make other choices later.",
        "",
        "Core prices are incremental. Optional +cost includes components and rebuys. An upgrade consumes its component and credits its cost.",
        "",
    ]
    lines.extend(_variant_markdown(guide))
    lines.extend(["## Purchase path and choices", ""])
    for index in range(len(guidance.default_path.actions) + 1):
        if index:
            step = guidance.default_path.actions[index - 1]
            lines.extend([
                f"**{index}. {step.name} — {step.incremental_cost:,} souls**",
                "",
            ])
        for decision in guidance.decisions:
            if decision.after_step == index:
                lines.extend(_decision(guidance, decision))
    lines.extend(_unplaced(guidance))
    if guide.core_alternatives:
        lines.extend(["## Optional core substitutions", ""])
        lines.extend(
            f"- **{guidance.names[alternative.item_id]}** replaces **{guidance.names[alternative.comparator_item_id]}**. {alternative.when} {alternative.skip}"
            for alternative in guide.core_alternatives
        )
        lines.append("")
    lines.extend([
        "## Item pool",
        "",
        "These tiers contain the full pool. They are not a purchase order.",
        "",
    ])
    lines.extend(
        f"- **Tier {tier}:** "
        + (
            ", ".join(item.name for item in guide.tiers.get(tier, ()))
            or "No supported options are available"
        )
        + "."
        for tier in range(1, 5)
    )
    if details:
        lines.extend(["", *_details(guidance)])
    lines.extend([
        "",
        "Each choice keeps the core's upgrade lineages. Recalculate from actual inventory when you combine choices. Slots and active-item limits still apply.",
        "",
        guidance.evidence_basis
        + ". Automatic choices require admitted branch evidence.",
        "",
    ])
    if details:
        lines.extend(
            build_markdown(variant, details=True) for variant in guide.variant_guides
        )
    return "\n".join(lines)


def _variant_markdown(guide: PurchaseGuide) -> list[str]:
    if not guide.variant_guides:
        return []
    return [
        "",
        "## Core variants",
        "",
        VARIANT_RULE,
        "",
        *(
            f"- **Variant {index}:** {variant_changes(guide, variant)}. {variant.core_target_cost:,} souls; {variant.evidence_summary.get('status', 'observed')}."
            for index, variant in enumerate(guide.variant_guides, 1)
        ),
        "",
    ]


def _compact_markdown(guide: PurchaseGuide, guidance: PurchaseGuidance) -> str:
    lines = [
        f"# {guide.hero_name} — {guide.build_archetype}",
        "",
        f"Core: {guide.core_target_cost:,} souls. Ranks: {guide.rank_identity}.",
        f"Evidence: {guidance.evidence.get('status', 'observed')}. Limits: {guidance.evidence.get('limitations', [])}.",
        "",
        "Buy CORE in order. All other sections are optional. Tier numbers show prices, not purchase order.",
        "Variant items appear once in CORE OPTIONAL. Complete variant paths, pools, and purchase instructions are in the details file.",
        "",
    ]
    for category in guide.rendered_categories:
        lines.extend([f"## {category.name}", ""])
        if category.optional:
            lines.append(
                ", ".join(item.name for item in category.items)
                if category.items
                else "No supported options."
            )
        else:
            lines.extend(
                f"{index}. **{step.name}** — {step.incremental_cost:,} souls."
                for index, step in enumerate(guidance.default_path.actions, 1)
            )
        lines.append("")
    return "\n".join(lines)
