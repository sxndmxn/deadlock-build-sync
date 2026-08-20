from __future__ import annotations

import json
from typing import Any

_MECHANIC_TAG_PHRASES = {
    "melee": ("melee attack", "melee damage", "heavy melee", "light melee"),
    "charges": ("ability charge", "+1 charge", "charge delay"),
    "healing": ("heal", "healing", "lifesteal", "life steal"),
    "range": ("ability range", "increased range", "cast range", "radius"),
    "cooldown": ("cooldown", "recharge time"),
    "slow": ("movement slow", "move speed slow", "applies slow"),
    "stun": ("stun", "stunned", "knockup"),
    "bullet_resist": ("bullet resist", "bullet resistance"),
    "spirit_resist": ("spirit resist", "spirit resistance"),
    "weapon_damage": ("weapon damage", "bullet damage"),
    "spirit_damage": ("spirit damage",),
}
_MECHANIC_TAG_WEIGHTS = {
    "melee": 3,
    "charges": 2,
    "healing": 2,
    "range": 1,
    "cooldown": 1,
    "slow": 1,
    "stun": 1,
    "bullet_resist": 1,
    "spirit_resist": 1,
    "weapon_damage": 1,
    "spirit_damage": 1,
}


def asset_mechanics_refs(asset: dict[str, Any]) -> tuple[str, ...]:
    """Return stable source pointers without interpreting free-form mechanics prose.

    Returns:
        Asset field references suitable for a mechanical evidence claim.

    """
    item_id = int(asset["id"])
    refs = [f"asset:item:{item_id}"]
    if asset.get("description"):
        refs.append(f"asset:item:{item_id}:description")
    if asset.get("component_items"):
        refs.append(f"asset:item:{item_id}:components")
    return tuple(refs)


def _mechanic_tags(value: object) -> frozenset[str]:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True).casefold()
    return frozenset(
        tag
        for tag, phrases in _MECHANIC_TAG_PHRASES.items()
        if any(phrase in text for phrase in phrases)
    )


def hero_item_affinity_scores(
    hero: dict[str, Any], assets: list[dict[str, Any]]
) -> dict[int, int]:
    """Score explicit item/kit mechanic intersections from current asset prose.

    Returns:
        Item IDs mapped to controlled-vocabulary affinity scores.

    """
    assets_by_class = {
        str(asset["class_name"]): asset
        for asset in assets
        if isinstance(asset.get("class_name"), str)
    }
    signatures = hero.get("items")
    if not isinstance(signatures, dict):
        return {}
    ability_assets = [
        assets_by_class[class_name]
        for class_name in signatures.values()
        if isinstance(class_name, str) and class_name in assets_by_class
    ]
    hero_tags = _mechanic_tags([
        {"name": asset.get("name"), "description": asset.get("description")}
        for asset in ability_assets
    ])
    scores = {}
    for asset in assets:
        item_id = asset.get("id")
        if not isinstance(item_id, int):
            continue
        item_tags = _mechanic_tags({
            "name": asset.get("name"),
            "description": asset.get("description"),
        })
        score = sum(_MECHANIC_TAG_WEIGHTS[tag] for tag in hero_tags & item_tags)
        if score:
            scores[item_id] = score
    return scores
