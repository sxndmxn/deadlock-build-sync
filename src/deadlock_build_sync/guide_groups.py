"""Publish one default Queue with complete, separately supported variants."""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from typing import TYPE_CHECKING

from .artifacts import ArtifactError
from .purchase_categories import split_guidance
from .purchase_types import GuideCategory

if TYPE_CHECKING:
    from .purchase_types import GuideItem, PurchaseGuide


VARIANT_RULE = (
    "Choose one complete variant before purchase. The Queue follows the default. "
    "Use the selected variant's order and item pool. Core changes during a match "
    "still require admitted substitution evidence."
)


def variant_changes(default: PurchaseGuide, variant: PurchaseGuide) -> str:
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


def variant_record(guide: PurchaseGuide) -> dict[str, object]:
    return {
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


def group_record(guide: PurchaseGuide) -> dict[str, object]:
    return {
        "schema_version": 1,
        "group_id": guide.path_id,
        "default_path_id": guide.path_id,
        "variants": [
            variant_record(member) for member in (guide, *guide.variant_guides)
        ],
    }


def _variant_rows(default: PurchaseGuide) -> list[GuideCategory]:
    result: list[GuideCategory] = []
    for index, variant in enumerate(default.variant_guides, 1):
        evidence = variant.evidence_summary
        path = " -> ".join(item.name for item in variant.core_purchase_items)
        text = (
            f"{variant_changes(default, variant)}. Total: {variant.core_target_cost:,} souls. "
            f"Evidence: {evidence.get('status', 'observed')}; owners D/S/V: "
            f"{evidence.get('discovery_owners')}/{evidence.get('selection_owners')}/{evidence.get('validation_owners')}. "
            f"Complete order: {path}. Limits: {evidence.get('limitations', [])}. "
            f"Timing: {evidence.get('timing_status', 'uncertain')}. {VARIANT_RULE}"
        )
        added = tuple(
            item
            for item in variant.core_items
            if item.item_id not in default.signature_item_ids
        )
        result.extend(
            GuideCategory(
                f"VARIANT {index}" + (f" ({part + 1})" if part else ""),
                added if part == 0 else (),
                chunk,
                optional=True,
            )
            for part, chunk in enumerate(split_guidance(text))
        )
    return result


def _variant_pools(guide: PurchaseGuide) -> list[GuideCategory]:
    result: list[GuideCategory] = []
    for tier in range(1, 5):
        members: dict[tuple[int, int | None], tuple[GuideItem, list[str]]] = {}
        for index, variant in enumerate(guide.variant_guides, 1):
            for item in variant.tiers[tier]:
                key = item.item_id, item.imbue_target_ability_id
                members.setdefault(key, (item, []))[1].append(str(index))
        items = tuple(
            replace(
                item,
                annotation_text="Pool for variants "
                + ", ".join(indices)
                + ". Use that variant's timing and cost details.",
            )
            for item, indices in members.values()
        )
        result.append(
            GuideCategory(
                f"VARIANT POOLS | TIER {tier}",
                items,
                "Options are scoped to the listed variants. Each exact core keeps its own supported pool."
                if items
                else "No supported options are available.",
                optional=True,
            )
        )
    return result


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
            result.append(default)
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
    return replace(
        combined,
        categories=(
            *default.rendered_categories,
            *_variant_rows(combined),
            *_variant_pools(combined),
        ),
    )
