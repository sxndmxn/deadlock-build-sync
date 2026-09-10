"""Publish one default Queue with complete, separately supported variants."""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from typing import TYPE_CHECKING

from .artifacts import ArtifactError
from .beam_display import compact_beam_guide, generator_metadata
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


def _collect_optional_core_items(guide: PurchaseGuide) -> tuple[GuideItem, ...]:
    core_ids = {item.item_id for item in guide.core_purchase_items or guide.core_items}
    members = [
        (item, f"V{index}")
        for index, variant in enumerate(guide.variant_guides, 1)
        for item in variant.core_purchase_items or variant.core_items
        if item.item_id not in core_ids
    ]
    members.extend(
        (item, "Conditional Default" if index == 0 else f"Conditional V{index}")
        for index, variant in enumerate((guide, *guide.variant_guides))
        for item in variant.optional_core_items
        if item.item_id not in core_ids
    )
    optional_ids = {item.item_id for item, _ in members}
    members.extend(
        (item, "Pool Default" if index == 0 else f"Pool V{index}")
        for index, variant in enumerate((guide, *guide.variant_guides))
        for items in variant.tiers.values()
        for item in items
        if item.item_id in optional_ids
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
    optional = _collect_optional_core_items(guide)
    covered = {item.item_id for item in (*core, *optional)}
    result = [GuideCategory("CORE", core, compact=True)]
    if optional:
        result.append(
            GuideCategory("CORE OPTIONAL", optional, optional=True, compact=True)
        )
    for tier in range(1, 5):
        members = [
            (item, "Default" if index == 0 else f"V{index}")
            for index, variant in enumerate((guide, *guide.variant_guides))
            for item in variant.tiers[tier]
            if item.item_id not in covered
        ]
        items = _collect_variant_items(members)
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
                compact_beam_guide(default)
                if generator_metadata(default)
                else replace(default, categories=_build_compact_categories(default))
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
    if generator_metadata(combined):
        return compact_beam_guide(combined)
    return replace(combined, categories=_build_compact_categories(combined))
