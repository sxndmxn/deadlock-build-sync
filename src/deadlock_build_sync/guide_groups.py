"""Publish one default Queue with complete, separately supported variants."""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from typing import TYPE_CHECKING

from .artifacts import ArtifactError
from .beam_display import generator_metadata, variant_statistics
from .purchase_types import MAX_ITEM_ANNOTATION_BYTES, GuideCategory

if TYPE_CHECKING:
    from .purchase_types import GuideItem, PurchaseGuide


VARIANT_RULE = (
    "Choose one complete variant before purchase. The Queue follows the default. "
    "Use the selected variant's order and item pool. Core changes during a match "
    "still require admitted substitution evidence."
)


def describe_variant_changes(default: PurchaseGuide, variant: PurchaseGuide) -> str:
    original = {item.item_id for item in default.core_items}
    selected = {item.item_id for item in variant.core_items}
    added = ", ".join(
        item.name for item in variant.core_items if item.item_id not in original
    )
    removed = ", ".join(
        item.name for item in default.core_items if item.item_id not in selected
    )
    parts = [f"Use {added}" if added else "", f"omit {removed}" if removed else ""]
    return "; ".join(part for part in parts if part) or "Default core"


def build_variant_record(guide: PurchaseGuide) -> dict[str, object]:
    return {
        **(
            {"generator": generator_metadata(guide)}
            if generator_metadata(guide)
            else {}
        ),
        "path_id": guide.path_id,
        "policy_id": guide.policy_id,
        "core": [item.item_id for item in guide.core_items],
        "core_cost": guide.core_target_cost,
        "evidence": guide.evidence_summary,
        "cohort": guide.cohort.as_dict() if guide.cohort else {},
        "purchase_guidance": guide.purchase_guidance.as_dict()
        if guide.purchase_guidance
        else None,
        "item_pool": {
            str(tier): [item.item_id for item in items]
            for tier, items in guide.tiers.items()
        },
        "ability_order": list(guide.ability_path.ability_ids)
        if guide.ability_path
        else [],
    }


def build_group_record(guide: PurchaseGuide) -> dict[str, object]:
    return {
        "schema_version": 1,
        "group_id": guide.path_id,
        "default_path_id": guide.path_id,
        "variants": [
            build_variant_record(member) for member in (guide, *guide.variant_guides)
        ],
    }


def describe_variants(guide: PurchaseGuide) -> list[str]:
    return [
        f"V{index}: {describe_variant_changes(guide, variant)}. "
        f"{variant.core_target_cost:,} souls; {variant.evidence_summary.get('status', 'observed')}. "
        + " ".join(variant_statistics(variant, detailed=True))
        + " Order: "
        + " -> ".join(
            item.name
            + (
                f" [imbue {item.imbue_target_ability}]"
                if item.imbue_target_ability
                else ""
            )
            for item in variant.core_purchase_items
        )
        + "".join(
            f" Conditional core: {alternative.when} {alternative.swap}. {alternative.why} {alternative.skip}"
            for alternative in variant.core_alternatives
        )
        for index, variant in enumerate(guide.variant_guides, 1)
    ]


def _collect_variant_items(
    members: list[tuple[GuideItem, str]],
) -> tuple[GuideItem, ...]:
    grouped: dict[int, list[tuple[GuideItem, str]]] = {}
    for item, scope in members:
        grouped.setdefault(item.item_id, []).append((item, scope))
    result = []
    for rows in grouped.values():
        item = rows[0][0]
        scopes = ", ".join(dict.fromkeys(scope for _, scope in rows))
        targets = {value.imbue_target_ability_id for value, _ in rows}
        text = f"{scopes}. Stats: {rows[0][1]}.\n{item.annotation}"
        if len(targets) > 1:
            text = f"{scopes}. Imbue varies; use the selected variant's target."
        if len(text.encode()) > MAX_ITEM_ANNOTATION_BYTES:
            text = "Multiple variants; check the selected variant's full guide for scope, timing, and imbue target."
        result.append(
            replace(
                item,
                annotation_text=text,
                imbue_target_ability_id=item.imbue_target_ability_id
                if len(targets) == 1
                else None,
            )
        )
    return tuple(result)


def _collect_conditional_core_items(guide: PurchaseGuide) -> tuple[GuideItem, ...]:
    core_ids = {item.item_id for item in guide.core_purchase_items or guide.core_items}
    members = [
        (item, "Conditional Default" if index == 0 else f"Conditional V{index}")
        for index, variant in enumerate((guide, *guide.variant_guides))
        for item in variant.optional_core_items
        if item.item_id not in core_ids
    ]
    optional_ids = {item.item_id for item, _ in members}
    members.extend(
        (item, "Pool Default" if index == 0 else f"Pool V{index}")
        for index, variant in enumerate((guide, *guide.variant_guides))
        for items in variant.tiers.values()
        for item in items
        if item.item_id in optional_ids
    )
    return _collect_variant_items(members)


def _build_variant_categories(guide: PurchaseGuide) -> tuple[GuideCategory, ...]:
    if not guide.variant_guides:
        return ()
    shared = set.intersection(
        *(
            {item.item_id for item in member.core_items}
            for member in (guide, *guide.variant_guides)
        )
    )
    categories = []
    if shared:
        items = _collect_variant_items([
            (item, "Default" if index == 0 else f"V{index}")
            for index, member in enumerate((guide, *guide.variant_guides))
            for item in member.core_items
            if item.item_id in shared
        ])
        categories.append(
            GuideCategory(
                "SHARED CORE", items, "Variant base.", optional=True, compact=True
            )
        )
    for index, variant in enumerate(guide.variant_guides, 1):
        combination = tuple(
            item for item in variant.core_items if item.item_id not in shared
        )
        items = _collect_variant_items([
            (item, f"V{index}") for item in combination or variant.core_items
        ])
        categories.append(
            GuideCategory(
                f"VARIANT {index}",
                items,
                "SHARED CORE +" if shared and combination else "Full core.",
                optional=True,
                compact=True,
            )
        )
    return tuple(categories)


def _collect_tier_items(
    guide: PurchaseGuide, tier: int, covered: set[int]
) -> tuple[GuideItem, ...]:
    members = [
        (item, "Default" if index == 0 else f"V{index}")
        for index, variant in enumerate((guide, *guide.variant_guides))
        for item in variant.tiers[tier]
        if item.item_id not in covered
    ]
    for index, variant in enumerate(guide.variant_guides, 1):
        excluded = covered | {item.item_id for item in variant.core_items}
        members.extend(
            (item, f"Component V{index}")
            for item in variant.core_purchase_items
            if item.tier == tier and item.item_id not in excluded
        )
    return _collect_variant_items(members)


def _build_compact_categories(guide: PurchaseGuide) -> tuple[GuideCategory, ...]:
    if guide.purchase_guidance is None:
        return guide.rendered_categories
    core = tuple(
        replace(
            item,
            annotation_text=f"Step {index}: +{step.incremental_cost:,} souls; total {step.cumulative_cost:,}.\n{item.annotation}",
        )
        for index, (item, step) in enumerate(
            zip(
                guide.core_purchase_items or guide.core_items,
                guide.purchase_guidance.default_path.actions,
                strict=True,
            ),
            1,
        )
    )
    conditional = _collect_conditional_core_items(guide)
    result = [
        GuideCategory("CORE", core, "; ".join(variant_statistics(guide)), compact=True),
        *_build_variant_categories(guide),
    ]
    if conditional:
        result.append(
            GuideCategory("CORE CONDITIONAL", conditional, optional=True, compact=True)
        )
    covered = {item.item_id for item in (*core, *conditional)}
    for tier in range(1, 5):
        items = _collect_tier_items(guide, tier, covered)
        result.append(
            GuideCategory(
                f"TIER {tier}",
                items,
                "" if items else "No supported options.",
                optional=True,
                compact=True,
            )
        )
    return tuple(result)


def _collect_group_item_ids(guide: PurchaseGuide) -> set[int]:
    return {
        item.item_id
        for member in (guide, *guide.variant_guides)
        for item in (
            *(member.core_purchase_items or member.core_items),
            *member.optional_core_items,
            *(item for items in member.tiers.values() for item in items),
        )
    }


def validate_group_categories(guide: PurchaseGuide) -> None:
    """Reject incomplete grouped layouts before Steam serialization.

    Raises:
        ValueError: If panels, purchase order, or supported items differ.

    """
    categories = guide.rendered_categories
    guidance = guide.purchase_guidance
    if guidance is None or not any(category.compact for category in categories):
        return
    names = [category.name for category in categories]
    variants = _build_variant_categories(guide)
    expected_names = ["CORE", *(category.name for category in variants)]
    if _collect_conditional_core_items(guide):
        expected_names.append("CORE CONDITIONAL")
    expected_names.extend(f"TIER {tier}" for tier in range(1, 5))
    if names != expected_names:
        raise ValueError(
            "Steam build requires CORE, each variant, and all four tier panels"
        )
    if categories[1 : 1 + len(variants)] != variants:
        raise ValueError("Steam variant panels differ from complete core combinations")
    if any(
        category.optional != (index > 0) for index, category in enumerate(categories)
    ):
        raise ValueError("Steam tier and variant panels must remain optional")
    queued = tuple(item.item_id for item in categories[0].items)
    if queued != tuple(step.item_id for step in guidance.default_path.actions):
        raise ValueError("Steam Queue differs from the canonical component path")
    shown = {item.item_id for category in categories for item in category.items}
    if _collect_group_item_ids(guide) != shown:
        raise ValueError("Steam build items differ from the complete variant pools")


def group_guides(
    guides: list[PurchaseGuide], groups: dict[tuple[int, str], str]
) -> list[PurchaseGuide]:
    heroes = {guide.hero_id for guide in guides}
    present = {
        (guide.hero_id, member.path_id)
        for guide in guides
        for member in (guide, *guide.variant_guides)
    }
    if groups and present != {key for key in groups if key[0] in heroes}:
        raise ArtifactError("Guide groups do not cover every supported variant")
    by_group: dict[tuple[int, str], list[PurchaseGuide]] = {}
    for guide in guides:
        key = guide.hero_id, groups.get((guide.hero_id, guide.path_id), guide.path_id)
        by_group.setdefault(key, []).append(guide)
    result = []
    for (_, group_id), members in by_group.items():
        default = next((guide for guide in members if guide.path_id == group_id), None)
        if default is None:
            raise ArtifactError("Guide group has no supported default")
        if len(members) == 1:
            result.append(
                replace(default, categories=_build_compact_categories(default))
            )
            continue
        result.append(_combine_guides(default, members))
    return result


def _combine_guides(
    default: PurchaseGuide, members: list[PurchaseGuide]
) -> PurchaseGuide:
    variants = tuple(
        sorted(
            (guide for guide in members if guide is not default),
            key=lambda guide: guide.path_id,
        )
    )
    counts = Counter(item.item_id for guide in members for item in guide.core_items)
    names = {item.item_id: item.name for guide in members for item in guide.core_items}
    label = " / ".join(
        names[item]
        for item in sorted(counts, key=lambda item: (-counts[item], item))[:2]
    )
    combined = replace(
        default, variant_guides=variants, path_label=label, build_archetype=label
    )
    return replace(combined, categories=_build_compact_categories(combined))
