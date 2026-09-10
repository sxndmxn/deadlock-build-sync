"""Project complete beam variants into bounded native categories and Markdown."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from .build_support import numeric
from .purchase_types import MAX_CATEGORY_DESCRIPTION_BYTES, GuideCategory
from .value_validation import object_dict, object_list

if TYPE_CHECKING:
    from .purchase_types import PurchaseGuide

STATE_LABELS = {0: "Behind", 1: "Even", 2: "Ahead"}
COMPACT_WIDTH = 900.0
COMPACT_HEIGHT = 650.0


def generator_metadata(guide: PurchaseGuide) -> dict[str, object]:
    return object_dict(guide.evidence_summary.get("generator")) or {}


def variant_state_label(guide: PurchaseGuide) -> str:
    states = object_list(generator_metadata(guide).get("states")) or []
    return "/".join(
        STATE_LABELS[value]
        for value in states
        if type(value) is int and value in STATE_LABELS
    )


def variant_statistics(guide: PurchaseGuide, *, detailed: bool = False) -> list[str]:
    evidence = object_dict(generator_metadata(guide).get("state_evidence")) or {}
    lines = []
    for state, label in STATE_LABELS.items():
        folds = object_dict(evidence.get(str(state))) or {}
        row = object_dict(folds.get("validation")) or {}
        count, wins = row.get("owners"), row.get("wins")
        if type(count) is not int or type(wins) is not int or not count:
            continue
        text = f"{label}: {100 * wins / count:.1f}% | {wins}/{count} wins"
        if detailed:
            text += (
                f" | 95% interval {100 * numeric(row, 'lower_95'):.1f}%–{100 * numeric(row, 'upper_95'):.1f}%."
                f" State hero baseline: {100 * numeric(row, 'hero_win_rate'):.1f}% across {row['hero_matches']} matches."
            )
        lines.append(text)
    return lines


def category_extent(categories: tuple[GuideCategory, ...]) -> tuple[float, float]:
    x = y = row_height = width = 0.0
    for category in categories:
        gap = 12.0 if x else 0.0
        if x and x + gap + category.width > COMPACT_WIDTH:
            y += row_height + 12.0
            x = row_height = gap = 0.0
        x += gap + category.width
        row_height = max(row_height, category.height)
        width = max(width, x)
    return width, y + row_height


def fits_categories(categories: tuple[GuideCategory, ...]) -> bool:
    width, height = category_extent(categories)
    return width <= COMPACT_WIDTH and height <= COMPACT_HEIGHT


def variant_category(
    guide: PurchaseGuide, shared: frozenset[int], index: int
) -> GuideCategory | None:
    route = " > ".join(item.name for item in guide.core_purchase_items)
    description = (
        "Complete option. " + "; ".join(variant_statistics(guide)) + ". Order: " + route
    )
    if len(description.encode()) > MAX_CATEGORY_DESCRIPTION_BYTES:
        return None
    additions = tuple(item for item in guide.core_items if item.item_id not in shared)
    return GuideCategory(
        f"V{index} {variant_state_label(guide)}",
        additions,
        description,
        optional=True,
        compact=True,
    )


def append_default_tiers(
    guide: PurchaseGuide, categories: list[GuideCategory]
) -> set[int]:
    covered = {item.item_id for category in categories for item in category.items}
    for tier in range(1, 5):
        selected = ()
        for item in guide.tiers[tier]:
            if item.item_id in covered:
                continue
            candidate = GuideCategory(
                f"TIER {tier} DEFAULT", (*selected, item), optional=True, compact=True
            )
            if fits_categories((*categories, candidate)):
                selected = (*selected, item)
        if selected:
            categories.append(
                GuideCategory(
                    f"TIER {tier} DEFAULT",
                    selected,
                    "Optional items for the default core. Use the complete guide for other variant pools.",
                    optional=True,
                    compact=True,
                )
            )
            covered.update(item.item_id for item in selected)
    return covered


def compact_beam_guide(guide: PurchaseGuide) -> PurchaseGuide:
    members = (guide, *guide.variant_guides)
    shared = frozenset.intersection(
        *(frozenset(item.item_id for item in member.core_items) for member in members)
    )
    categories = [
        GuideCategory(
            "CORE",
            guide.core_purchase_items,
            "; ".join(variant_statistics(guide))
            or "Current-guide fallback. Check cash before purchase.",
            compact=True,
        )
    ]
    if shared and guide.variant_guides:
        categories.append(
            GuideCategory(
                "CORE REFERENCE",
                tuple(item for item in guide.core_items if item.item_id in shared),
                "Every option requires these final items. Use each option's complete order. The Queue follows CORE.",
                optional=True,
                compact=True,
            )
        )
    shown = []
    for index, member in enumerate(guide.variant_guides, 1):
        category = variant_category(member, shared, index)
        if category is not None and fits_categories((*categories, category)):
            categories.append(category)
            shown.append(member.path_id)
    covered = append_default_tiers(guide, categories)
    return replace(
        guide,
        categories=tuple(categories),
        evidence_summary={
            **guide.evidence_summary,
            "display": {
                "target_width": COMPACT_WIDTH,
                "target_height": COMPACT_HEIGHT,
                "extent": category_extent(tuple(categories)),
                "overflow": not fits_categories(tuple(categories)),
                "shown_variants": shown,
                "omitted_variants": len(guide.variant_guides) - len(shown),
                "omitted_tier_items": sum(
                    item.item_id not in covered
                    for items in guide.tiers.values()
                    for item in items
                ),
                "live_client_verified": False,
            },
        },
    )


def render_beam_markdown(guide: PurchaseGuide) -> str:
    lines = [
        f"# {guide.hero_name} — {guide.build_archetype}",
        "",
        "One default Queue. Core options are complete alternatives.",
        "Wealth states compare personal net worth with the lobby average.",
        "Behind: below 90%. Even: 90% through 110%. Ahead: above 110%.",
        "State labels describe observed core ownership. They do not authorize a mid-match core switch.",
        "",
    ]
    members = (guide, *guide.variant_guides)
    shared = set.intersection(
        *({item.item_id for item in member.core_items} for member in members)
    )
    if shared and len(members) > 1:
        lines.extend([
            "**Shared final items:** "
            + " · ".join(
                item.name for item in guide.core_items if item.item_id in shared
            ),
            "",
        ])
    for index, member in enumerate(members):
        label = "Default" if index == 0 else f"Variant {index}"
        metadata = generator_metadata(member)
        lines.extend([
            f"## {label} — {variant_state_label(member)}",
            "",
            "**Final core:** " + " · ".join(item.name for item in member.core_items),
            "**Purchase order:** "
            + " → ".join(item.name for item in member.core_purchase_items),
            f"**Total cost:** {member.core_target_cost:,} souls.",
            *variant_statistics(member, detailed=True),
        ])
        if metadata.get("effective") == "current":
            lines.append(f"Current-guide fallback: {metadata.get('fallback_reason')}")
        lines.append("")
        lines.extend(
            f"- **Tier {tier} options:** "
            + (
                " · ".join(item.name for item in member.tiers[tier])
                or "No supported options."
            )
            for tier in range(1, 5)
        )
        lines.extend(render_ability_instructions(member))
        lines.append("")
    lines.extend([
        "Rates describe validation matches with all final core items owned strictly before 20 minutes. Additional items are permitted.",
        "Variant samples can overlap. These observations do not prove a purchase-order or win-rate benefit.",
        "Tier rows are optional item pools. Check each selected route's cash, timing, and inventory requirements.",
        "The details file contains complete purchase choices, intervals, and supporting evidence.",
        "The native display contains selected options. This file includes every admitted variant and its complete item pool.",
        "",
    ])
    return "\n".join(lines)


def render_ability_instructions(member: PurchaseGuide) -> list[str]:
    lines = []
    if member.ability_path:
        names = object_dict(member.evidence_summary.get("ability_names")) or {}
        lines.extend([
            "",
            "**Ability order:** "
            + " → ".join(
                str(names.get(str(item), item))
                for item in member.ability_path.ability_ids
            ),
            "Ability evidence: "
            + (
                member.ability_path.fallback_reason
                or "Build-conditioned observed order."
            ),
        ])
    imbues = {
        item.name: item.imbue_target_ability
        for item in (
            *member.core_purchase_items,
            *(item for items in member.tiers.values() for item in items),
        )
        if item.imbue_target_ability
    }
    lines.extend(f"- Imbue {item}: {ability}." for item, ability in imbues.items())
    return lines
