"""Source-backed descriptive mechanic focus; no inferred synergy weights."""

from __future__ import annotations

from deadlock_build_sync.mechanics_assets import clean_mechanical_text
from deadlock_build_sync.mechanics_compatibility import (
    _MECHANIC_TAG_PHRASES,  # ruff: ignore[import-private-name] -- Reuse the existing controlled vocabulary without a production API change.
)


def description_text(value: object) -> str:
    if isinstance(value, dict):
        return " ".join(description_text(part) for part in value.values())
    if isinstance(value, (list, tuple)):
        return " ".join(description_text(part) for part in value)
    return clean_mechanical_text(str(value)) if value is not None else ""


def channels(asset: dict) -> dict[str, dict]:
    text = description_text(asset.get("description"))
    lower = text.casefold()
    return {
        channel: {
            "asset_id": asset["id"],
            "name": asset.get("name"),
            "ref": f"asset:item:{asset['id']}:description",
            "matched_phrases": [phrase for phrase in phrases if phrase in lower],
            "description": text,
        }
        for channel, phrases in _MECHANIC_TAG_PHRASES.items()
        if any(phrase in lower for phrase in phrases)
    }


def explain(hero: dict, items: list[int], assets: list[dict]) -> dict:
    by_id = {asset["id"]: asset for asset in assets}
    by_class = {asset.get("class_name"): asset for asset in assets}
    signatures = hero.get("items", {})
    abilities = [
        by_class[value]
        for key, value in signatures.items()
        if str(key).startswith("signature") and value in by_class
    ]
    kit = [channels(ability) for ability in abilities]
    item_channels = {item: channels(by_id[item]) for item in items}
    focuses = []
    for channel in _MECHANIC_TAG_PHRASES:
        supporting = [
            value[channel] for value in item_channels.values() if channel in value
        ]
        ability_refs = [value[channel] for value in kit if channel in value]
        if len(supporting) >= 2 and ability_refs:
            focuses.append({
                "channel": channel,
                "items": supporting,
                "abilities": ability_refs,
            })
    return {
        "supported_focus": bool(focuses),
        "focuses": focuses,
        "item_evidence": {str(item): value for item, value in item_channels.items()},
        "reason": None
        if focuses
        else "No shared documented kit channel supported by two core items",
        "limitation": "Textual mechanic overlap is a review aid, not measured synergy or a verified interaction",
    }
