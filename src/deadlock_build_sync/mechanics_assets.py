from __future__ import annotations

import html
import re

from .snapshot import sha256_json

BASE_INVENTORY_SLOTS = 9
MAX_FLEX_SLOTS = 3
MAX_ACTIVE_ITEMS = 4
DEFAULT_ABILITY_UPGRADE_COSTS = (1, 2, 5)

_TAG_PATTERN = re.compile(r"<[^>]+>")
_TOKEN_PATTERN = re.compile(r"\{[a-zA-Z0-9_.:-]+\}")
_SPACE_PATTERN = re.compile(r"\s+")


class MechanicsError(ValueError):
    """Raised when pinned mechanics are missing, contradictory, or illegal."""


def _is_populated(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, (str, list, tuple, dict)):
        return bool(value)
    return True


def clean_mechanical_text(value: object) -> str:
    """Normalize localized mechanics text while retaining its meaning.

    Returns:
        Plain single-line text with markup and unresolved template tokens removed.

    """
    if not isinstance(value, str):
        return ""
    unescaped = html.unescape(value)
    without_markup = _TAG_PATTERN.sub(" ", unescaped)
    without_tokens = _TOKEN_PATTERN.sub(" ", without_markup)
    return _SPACE_PATTERN.sub(" ", without_tokens).strip()


def normalize_mechanical_value(value: object) -> object:
    """Recursively normalize a mechanics payload without dropping populated fields.

    Returns:
        A JSON-compatible value with deterministic text and key ordering.

    """
    if isinstance(value, dict):
        return {
            str(key): normalize_mechanical_value(nested)
            for key, nested in sorted(value.items(), key=lambda pair: str(pair[0]))
            if _is_populated(nested)
        }
    if isinstance(value, list):
        return [normalize_mechanical_value(nested) for nested in value]
    if isinstance(value, tuple):
        return [normalize_mechanical_value(nested) for nested in value]
    if isinstance(value, str):
        cleaned = clean_mechanical_text(value)
        return cleaned or value.strip()
    return value


def normalize_hero_description(value: object) -> dict[str, str]:
    """Preserve each non-empty lore, role, playstyle, or description field.

    Returns:
        A keyed description rather than a lossy concatenated string.

    """
    if isinstance(value, str):
        cleaned = clean_mechanical_text(value)
        return {"summary": cleaned} if cleaned else {}
    if not isinstance(value, dict):
        return {}
    result: dict[str, str] = {}
    for key, nested in sorted(value.items(), key=lambda pair: str(pair[0])):
        cleaned = clean_mechanical_text(nested)
        if cleaned:
            result[str(key)] = cleaned
    return result


MECHANICS_FIELDS = (
    "ability_type",
    "behaviour",
    "cast_range",
    "channel_time",
    "component_items",
    "cooldown",
    "cost",
    "cost_bonuses",
    "damage_type",
    "description",
    "duration",
    "imbue",
    "is_active_item",
    "is_unique",
    "item_slot_type",
    "item_tier",
    "level_info",
    "max_count",
    "properties",
    "radius",
    "scaling_stats",
    "targeting",
    "unlock_level",
    "upgrade_costs",
    "upgrades",
    "weapon_info",
)


def extract_asset_mechanics(asset: dict[str, object]) -> dict[str, object]:
    """Extract all claim-relevant structured mechanics from one asset.

    Returns:
        An identity-bearing normalized mechanics record.

    Raises:
        MechanicsError: If the asset has no stable numeric identity.

    """
    asset_id = asset.get("id")
    if not isinstance(asset_id, int):
        raise MechanicsError("mechanics asset is missing a numeric id")
    result: dict[str, object] = {
        "id": asset_id,
        "class_name": str(asset.get("class_name") or ""),
        "name": clean_mechanical_text(asset.get("name")) or f"Asset {asset_id}",
        "type": str(asset.get("type") or "unknown"),
    }
    for field in MECHANICS_FIELDS:
        value = asset.get(field)
        if _is_populated(value):
            result[field] = normalize_mechanical_value(value)
    return result


def build_hero_mechanics(
    hero: dict[str, object],
    assets: list[dict[str, object]],
) -> dict[str, object]:
    """Create a complete, fingerprinted kit record from pinned asset payloads.

    Returns:
        Hero description, level scaling, and four resolved signature abilities.

    Raises:
        MechanicsError: If a signature reference is missing or malformed.

    """
    hero_id = hero.get("id")
    if not isinstance(hero_id, int):
        raise MechanicsError("hero asset is missing a numeric id")
    by_class = {
        str(asset["class_name"]): asset
        for asset in assets
        if isinstance(asset.get("class_name"), str)
    }
    references = hero.get("items")
    if not isinstance(references, dict):
        raise MechanicsError(f"hero {hero_id} has no signature ability mapping")
    abilities: list[dict[str, object]] = []
    for slot in range(1, 5):
        class_name = references.get(f"signature{slot}")
        if not isinstance(class_name, str) or class_name not in by_class:
            raise MechanicsError(f"hero {hero_id} is missing signature ability {slot}")
        record = extract_asset_mechanics(by_class[class_name])
        record["slot"] = slot
        abilities.append(record)
    result: dict[str, object] = {
        "hero_id": hero_id,
        "name": clean_mechanical_text(hero.get("name")) or f"Hero {hero_id}",
        "class_name": str(hero.get("class_name") or ""),
        "description": normalize_hero_description(hero.get("description")),
        "abilities": abilities,
    }
    for field in ("scaling_stats", "starting_stats", "level_info", "cost_bonuses"):
        value = hero.get(field)
        if _is_populated(value):
            result[field] = normalize_mechanical_value(value)
    result["mechanics_sha256"] = sha256_json(result)
    return result
