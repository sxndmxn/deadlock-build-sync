from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

from .purchase_guide import (
    GuideCategory,
    GuideItem,
    PurchaseGuide,
    tactical_item_annotation,
)


def _asset_text(asset: dict[str, Any]) -> str:
    return json.dumps(asset, sort_keys=True, ensure_ascii=False).casefold()


def mechanics_job(asset: dict[str, Any], item: GuideItem) -> str:
    """Classify one item from explicit pinned mechanics, with a neutral fallback.

    Returns:
        A short non-causal player-facing job label.

    """
    text = _asset_text(asset)
    rules = (
        (
            "Healing reduction",
            ("healing reduction", "heal amp receive penalty", "anti-heal"),
        ),
        ("Bullet defense", ("bullet resist", "bullet_resist", "weapon damage resist")),
        ("Spirit defense", ("spirit resist", "spirit_resist")),
        ("Mobility", ("move speed", "movespeed", "dash", "teleport", "leap")),
        (
            "Ally protection",
            (
                "target ally",
                "allied target",
                "ally shield",
                "ally barrier",
                "shield an ally",
            ),
        ),
    )
    for label, terms in rules:
        if any(term in text for term in terms):
            return label
    if item.imbue_target_ability_id is not None or "imbue" in text:
        return "Imbue"
    if bool(asset.get("is_active_item")):
        return "Active use"
    if asset.get("component_items"):
        if item.tier == 4:
            return "Slot consolidation"
        return "Upgrade"
    return "Reference option"


def _instruction(asset: dict[str, Any], item: GuideItem) -> str:
    parts = [f"Job: {mechanics_job(asset, item)}."]
    if item.required_flex_slots:
        parts.append(f"Requires {item.required_flex_slots} flex slot(s).")
    if item.sell_priority:
        parts.append(f"Replacement: sell priority {item.sell_priority}.")
    if item.imbue_target_ability_id is not None:
        parts.append(f"Imbue ability {item.imbue_target_ability_id}.")
    if bool(asset.get("is_active_item")):
        parts.append("Uses an active binding.")
    components = asset.get("component_items")
    if isinstance(components, list) and components:
        parts.append(f"Consumes {len(components)} component(s).")
    return " ".join(parts)


def annotate_optional_items(
    guide: PurchaseGuide,
    assets: list[dict[str, Any]],
) -> PurchaseGuide:
    """Apply mechanics-first action lines to optional rows.

    Returns:
        A guide with the same layout and mechanics-grounded optional annotations.

    Raises:
        ValueError: If a projected item is missing from the pinned asset catalog.

    """
    by_id = {
        int(asset["id"]): asset
        for asset in assets
        if isinstance(asset.get("id"), int) and not isinstance(asset.get("id"), bool)
    }
    replacements: dict[int, GuideItem] = {}
    categories: list[GuideCategory] = []
    for category in guide.rendered_categories:
        items: list[GuideItem] = []
        for item in category.items:
            if not category.optional:
                items.append(item)
                continue
            if item.tactical_annotation:
                replacements[item.item_id] = item
                items.append(item)
                continue
            asset = by_id.get(item.item_id)
            if asset is None:
                raise ValueError(f"optional item {item.item_id} is missing from assets")
            annotated = replace(
                item,
                tactical_annotation=tactical_item_annotation(
                    _instruction(asset, item),
                    item,
                ),
            )
            replacements[item.item_id] = annotated
            items.append(annotated)
        categories.append(replace(category, items=tuple(items)))
    tiers = {
        tier: tuple(replacements.get(item.item_id, item) for item in items)
        for tier, items in guide.tiers.items()
    }
    return replace(guide, categories=tuple(categories), tiers=tiers)
