from __future__ import annotations

import html
import json
import math
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

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


def normalize_mechanical_value(value: Any) -> Any:
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


def extract_asset_mechanics(asset: dict[str, Any]) -> dict[str, Any]:
    """Extract all claim-relevant structured mechanics from one asset.

    Returns:
        An identity-bearing normalized mechanics record.

    Raises:
        MechanicsError: If the asset has no stable numeric identity.

    """
    asset_id = asset.get("id")
    if not isinstance(asset_id, int):
        raise MechanicsError("mechanics asset is missing a numeric id")
    result: dict[str, Any] = {
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
    hero: dict[str, Any],
    assets: list[dict[str, Any]],
) -> dict[str, Any]:
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
    abilities: list[dict[str, Any]] = []
    for slot in range(1, 5):
        class_name = references.get(f"signature{slot}")
        if not isinstance(class_name, str) or class_name not in by_class:
            raise MechanicsError(f"hero {hero_id} is missing signature ability {slot}")
        record = extract_asset_mechanics(by_class[class_name])
        record["slot"] = slot
        abilities.append(record)
    result: dict[str, Any] = {
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


def classify_item_threat_responses(asset: dict[str, Any]) -> frozenset[str]:
    """Map only explicit current item mechanics to conservative threat classes.

    Returns:
        Threats for which the asset text contains a direct response mechanic.

    """
    responses = set(_response_mechanic_labels(asset))
    normalized = canonical_mechanics_text(_material_observed_mechanics(asset))
    if _has_ally_target(normalized) and any(
        phrase in normalized for phrase in ("shield", "heal", "resist")
    ):
        responses.add("ally_protection")
    return frozenset(responses)


_CONDITIONAL_RESPONSE_COPY = {
    "spirit_burst": (
        "Heavy Spirit damage",
        "Before the next Spirit-heavy fight",
    ),
    "bullet_pressure": (
        "Heavy bullet damage",
        "Before the next bullet-heavy fight",
    ),
    "healing": (
        "Heavy enemy healing",
        "Before the next fight with heavy enemy healing",
    ),
    "hard_control": (
        "Hard control or debuffs",
        "Before entering the next control-heavy fight",
    ),
    "mobility_denial": (
        "Slows or movement denial",
        "Before the next fight with heavy slows",
    ),
    "slow_resistance": (
        "Enemy slows or movement denial",
        "Before the next fight with heavy slows",
    ),
    "ally_protection": (
        "A focused ally needs protection",
        "Before the ally commits to the next fight",
    ),
}
_CONDITIONAL_RESPONSE_PRIORITY = (
    "spirit_burst",
    "bullet_pressure",
    "healing",
    "hard_control",
    "slow_resistance",
    "mobility_denial",
    "ally_protection",
)
_RESPONSE_MECHANIC_COPY = (
    ("spirit resist", "Spirit Resist"),
    ("spirit shield", "Spirit Shield"),
    ("debuff resist", "Debuff Resist"),
    ("debuff immunity", "Debuff Immunity"),
    ("control immunity", "Control Immunity"),
    ("unstoppable", "Unstoppable"),
    ("bullet resist", "Bullet Resist"),
    ("bullet shield", "Bullet Shield"),
    ("weapon damage resistance", "Weapon Damage Resistance"),
    ("healing reduction", "Healing Reduction"),
    ("reduce healing", "Healing Reduction"),
    ("anti-heal", "Healing Reduction"),
    ("remove all negative", "Negative Effect Removal"),
    ("slow immunity", "Slow Immunity"),
    ("movement slow resistance", "Movement Slow Resist"),
    ("ground", "Ground"),
    ("disarm", "Disarm"),
    ("movement slow", "Movement Slow"),
)
_RESPONSE_BY_MECHANIC_PHRASE = {
    "spirit resist": "spirit_burst",
    "spirit shield": "spirit_burst",
    "debuff resist": "hard_control",
    "debuff immunity": "hard_control",
    "control immunity": "hard_control",
    "unstoppable": "hard_control",
    "remove all negative": "hard_control",
    "bullet resist": "bullet_pressure",
    "bullet shield": "bullet_pressure",
    "weapon damage resistance": "bullet_pressure",
    "healing reduction": "healing",
    "reduce healing": "healing",
    "anti-heal": "healing",
    "slow immunity": "slow_resistance",
    "movement slow resistance": "slow_resistance",
    "ground": "mobility_denial",
    "disarm": "mobility_denial",
    "movement slow": "mobility_denial",
}
_COMPARATOR_PURPOSES = (
    (("teleport", "pull", "ground", "disarm"), "catch"),
    (("bullet resist", "spirit resist", "shield"), "survival"),
    (("cooldown", "recharge"), "ability uptime"),
    (("weapon damage", "bullet damage", "fire rate"), "weapon pressure"),
    (("spirit damage", "spirit power"), "Spirit pressure"),
    (("heal", "lifesteal", "life steal"), "sustain"),
    (("melee",), "melee pressure"),
    (("range",), "range"),
    (("slow", "stun", "silence", "root"), "control"),
)


def conditional_item_decision(
    asset: dict[str, Any],
    comparator: dict[str, Any],
    *,
    response: str | None = None,
) -> tuple[str, str, str, str] | None:
    """Build grounded VS, WHY, WHEN, and SKIP fields from pinned mechanics.

    Returns:
        The four fields, or ``None`` when either item purpose is not explicit.

    """
    responses = classify_item_threat_responses(asset)
    selected = response or next(
        (
            candidate
            for candidate in _CONDITIONAL_RESPONSE_PRIORITY
            if candidate in responses
        ),
        None,
    )
    if (
        selected is None
        or selected not in responses
        or selected not in _CONDITIONAL_RESPONSE_COPY
    ):
        return None
    item_text = canonical_mechanics_text(_material_observed_mechanics(asset))
    response_labels = _response_mechanic_labels(asset)
    mechanics = list(response_labels[selected])
    for candidate in _CONDITIONAL_RESPONSE_PRIORITY:
        if candidate == "ally_protection" and selected != candidate:
            continue
        for label in response_labels.get(candidate, ()):
            if label not in mechanics:
                mechanics.append(label)
    if not mechanics:
        return None
    friendly = _has_ally_target(item_text)
    self_cast = "self cast" in item_text or "self-cast" in item_text
    target = (
        " for self/ally" if friendly and self_cast else " for ally" if friendly else ""
    )
    why = " and ".join(mechanics[:3]) + target

    comparator_text = canonical_mechanics_text(_material_observed_mechanics(comparator))
    purpose = next(
        (
            label
            for phrases, label in _COMPARATOR_PURPOSES
            if any(phrase in comparator_text for phrase in phrases)
        ),
        None,
    )
    if purpose is None:
        return None
    vs, when = _CONDITIONAL_RESPONSE_COPY[selected]
    if selected == "mobility_denial" and any(
        phrase in item_text
        for phrase in (
            "become grounded",
            "causes grounded",
            "ground, slow",
            "disarm",
            "applies slow",
        )
    ):
        vs = "Enemy escape or mobility"
        when = "Before fighting an evasive target"
    return vs, why, when, f"Keep default when {purpose} matters more"


_OBSERVED_ITEM_THREAT_PHRASES = {
    "bullet_pressure": ("bullet damage", "weapon damage"),
    "spirit_pressure": ("spirit damage", "spirit power"),
    "control": (
        "apply a stun",
        "applies a stun",
        "silences the target",
        "immobilizes",
        "become rooted",
    ),
    "mobility_escape": ("dash", "teleport", "leap", "blink"),
    "mobility_denial": (
        "applies a movement slow",
        "applies movement slow",
        "become grounded",
        "causes grounded",
    ),
    "ally_protection": (
        "target ally",
        "allied target",
        "shield an ally",
        "ally barrier",
    ),
}


def _active_property_mechanics(asset: dict[str, Any]) -> dict[str, Any]:
    raw_properties = asset.get("properties")
    if not isinstance(raw_properties, dict):
        return {}
    active: dict[str, Any] = {}
    for name, raw_property in raw_properties.items():
        if not isinstance(raw_property, dict) or "value" not in raw_property:
            continue
        value = raw_property["value"]
        disabled_value = raw_property.get("disable_value")
        if disabled_value is not None and str(value) == str(disabled_value):
            continue
        if value is None or (
            isinstance(value, (str, int, float)) and str(value) in {"", "0", "0.0"}
        ):
            continue
        active[str(name)] = {
            key: raw_property[key]
            for key in (
                "css_class",
                "label",
                "postvalue_label",
                "provided_property_type",
                "tooltip_is_elevated",
                "tooltip_is_important",
                "tooltip_section",
                "usage_flags",
                "value",
            )
            if key in raw_property
        }
    return active


def _base_description(asset: dict[str, Any]) -> object:
    description = asset.get("description")
    if isinstance(description, dict):
        return {
            key: description[key]
            for key in ("desc", "passive", "active")
            if _is_populated(description.get(key))
        }
    return description


def _important_property_mechanics(asset: dict[str, Any]) -> dict[str, Any]:
    return {
        name: value
        for name, value in _active_property_mechanics(asset).items()
        if value.get("tooltip_is_important") is True
    }


def _is_resistance_reduction_property(name: str, value: dict[str, Any]) -> bool:
    identity = " ".join((
        name,
        str(value.get("label") or ""),
        str(value.get("provided_property_type") or ""),
    )).casefold()
    return "resist" in identity and (
        "reduction" in identity or str(value.get("value") or "").startswith("-")
    )


def _response_property_mechanics(asset: dict[str, Any]) -> dict[str, Any]:
    return {
        name: value
        for name, value in _important_property_mechanics(asset).items()
        if not _is_resistance_reduction_property(name, value)
    }


def _visible_property_mechanics(asset: dict[str, Any]) -> dict[str, Any]:
    return {
        name: value
        for name, value in _active_property_mechanics(asset).items()
        if value.get("tooltip_is_important") is True
        or value.get("tooltip_is_elevated") is True
    }


def _material_observed_mechanics(asset: dict[str, Any]) -> dict[str, Any]:
    mechanics = extract_asset_mechanics(asset)
    observed: dict[str, Any] = {}
    description = _base_description(asset)
    if _is_populated(description):
        observed["description"] = normalize_mechanical_value(description)
    for key in ("behaviour", "damage_type", "targeting", "weapon_info"):
        if key in mechanics:
            observed[key] = mechanics[key]
    important_properties = _response_property_mechanics(asset)
    if important_properties:
        observed["properties"] = normalize_mechanical_value(important_properties)
    return observed


def _optional_observed_mechanics(asset: dict[str, Any]) -> dict[str, Any]:
    observed = _material_observed_mechanics(asset)
    visible_properties = _visible_property_mechanics(asset)
    if visible_properties:
        observed["properties"] = normalize_mechanical_value(visible_properties)
    return observed


_RESISTANCE_REDUCTION_WORDS = (
    "reduce",
    "reduces",
    "reduced",
    "reduction",
    "lower",
    "lowers",
    "lowered",
    "remove",
    "removes",
    "enemy",
    "enemies",
)


def _has_positive_resistance_text(text: str, phrase: str) -> bool:
    start = 0
    while (index := text.find(phrase, start)) >= 0:
        prefix = text[max(0, index - 48) : index]
        suffix = text[index + len(phrase) : index + len(phrase) + 24]
        if not any(
            re.search(rf"\b{re.escape(word)}\b", prefix)
            for word in _RESISTANCE_REDUCTION_WORDS
        ) and not re.search(r"\b(reduction|shred)\b", suffix):
            return True
        start = index + len(phrase)
    return False


def _has_control_immunity_text(text: str) -> bool:
    return "suppress negative status effects" in text or bool(
        re.search(
            r"\bimmune\b[^.!?]{0,96}\b(stun|silence|sleep|root|disarm)\b",
            text,
        )
    )


def _has_offensive_response_phrase(text: str, phrase: str) -> bool:
    """Check whether a control phrase is not part of defensive copy.

    Returns:
        True when at least one occurrence describes an offensive effect.

    """
    start = 0
    while (index := text.find(phrase, start)) >= 0:
        prefix = text[max(0, index - 96) : index]
        suffix = text[index + len(phrase) : index + len(phrase) + 24]
        defensive_prefix = re.search(
            r"\b(immune|immunity|resistant|resistance)\b[^.!?]{0,96}$",
            prefix,
        )
        defensive_suffix = (
            re.match(r"\s+resistance\b", suffix) if phrase == "movement slow" else None
        )
        if defensive_prefix is None and defensive_suffix is None:
            return True
        start = index + len(phrase)
    return False


def _important_property_labels(asset: dict[str, Any]) -> dict[str, tuple[str, ...]]:
    labels: dict[str, list[str]] = {}
    for prop in _response_property_mechanics(asset).values():
        property_type = str(prop.get("provided_property_type") or "").upper()
        label = clean_mechanical_text(prop.get("label"))
        normalized = canonical_mechanics_text(prop)
        response: str | None = None
        copy = label
        if "RESIST_REDUCTION" in property_type:
            continue
        if "BULLET_ARMOR_DAMAGE_RESIST" in property_type:
            response, copy = "bullet_pressure", "Bullet Resist"
        elif "BULLET_SHIELD" in property_type:
            response, copy = "bullet_pressure", label or "Bullet Shield"
        elif "FIRE_RATE_SLOW" in property_type:
            response, copy = "bullet_pressure", "Fire Rate Slow"
        elif "SPIRIT_ARMOR_DAMAGE_RESIST" in property_type:
            response, copy = "spirit_burst", "Spirit Resist"
        elif "SPIRIT_SHIELD" in property_type:
            response, copy = "spirit_burst", label or "Spirit Shield"
        elif "bullet shield" in normalized:
            response, copy = "bullet_pressure", label or "Bullet Shield"
        elif "spirit shield" in normalized:
            response, copy = "spirit_burst", label or "Spirit Shield"
        if response is not None and copy not in labels.setdefault(response, []):
            labels[response].append(copy)
    return {response: tuple(values) for response, values in labels.items()}


def _response_mechanic_labels(asset: dict[str, Any]) -> dict[str, tuple[str, ...]]:
    text = canonical_mechanics_text(_material_observed_mechanics(asset))
    labels = {
        key: list(value) for key, value in _important_property_labels(asset).items()
    }
    if _has_positive_resistance_text(text, "bullet resist"):
        labels.setdefault("bullet_pressure", []).append("Bullet Resist")
    if _has_positive_resistance_text(text, "spirit resist"):
        labels.setdefault("spirit_burst", []).append("Spirit Resist")
    if _has_control_immunity_text(text):
        labels.setdefault("hard_control", []).append("Control Immunity")
    for phrase, label in _RESPONSE_MECHANIC_COPY:
        if phrase not in text:
            continue
        if phrase in {
            "bullet resist",
            "spirit resist",
        } and not _has_positive_resistance_text(text, phrase):
            continue
        if phrase in {"ground", "disarm", "movement slow"} and not (
            _has_offensive_response_phrase(text, phrase)
        ):
            continue
        response = _RESPONSE_BY_MECHANIC_PHRASE[phrase]
        if label not in labels.setdefault(response, []):
            labels[response].append(label)
    if _has_ally_target(text) and any(
        phrase in text for phrase in ("shield", "heal", "resist")
    ):
        labels.setdefault("ally_protection", []).append("Ally Protection")
    return {
        response: tuple(dict.fromkeys(values))
        for response, values in labels.items()
        if values
    }


def _has_ally_target(text: str) -> bool:
    return bool(re.search(r"\bally\b|\bfriendly target\b", text))


def classify_observed_item_threats(asset: dict[str, Any]) -> frozenset[str]:
    """Classify only explicit threat mechanics on an observed enemy item.

    Returns:
        Conservative threat labels supported by the pinned item text.

    """
    normalized = canonical_mechanics_text(_material_observed_mechanics(asset))
    threats = {
        threat
        for threat, phrases in _OBSERVED_ITEM_THREAT_PHRASES.items()
        if any(phrase in normalized for phrase in phrases)
    }
    healing_response = any(
        phrase in normalized
        for phrase in ("healing reduction", "reduce healing", "anti-heal")
    )
    healing = any(
        phrase in normalized
        for phrase in ("restore health", "health regen", "healing amp", "heal an ally")
    )
    if healing and not healing_response:
        threats.add("healing")
    return frozenset(threats)


_OPTIONAL_PURPOSE_COPY = {
    "bullet defense": (
        "Enemy bullet pressure is material",
        "Spirit defense or CORE timing matters more",
    ),
    "spirit defense": (
        "Enemy Spirit burst is material",
        "Bullet defense or CORE timing matters more",
    ),
    "control defense": (
        "Enemy control blocks your next commit",
        "Damage or mobility matters more",
    ),
    "anti-heal": (
        "Enemy healing is material",
        "Healing is not changing the fight",
    ),
    "ally protection": (
        "A focused ally needs protection",
        "Your own survival matters more",
    ),
    "sustain": (
        "You need sustain between fights",
        "Immediate damage or defense matters more",
    ),
    "ability uptime": (
        "Your abilities need more uptime",
        "One-fight power matters more",
    ),
    "mobility": (
        "You need safer entry or escape",
        "You can already reach and leave fights",
    ),
    "control/catch": (
        "Your team needs reliable catch",
        "Targets cannot escape your team",
    ),
    "melee": (
        "You can safely force melee range",
        "You cannot stay in melee range",
    ),
    "weapon pressure": (
        "Weapon pressure is your next priority",
        "Defense or Spirit pressure matters more",
    ),
    "Spirit pressure": (
        "Spirit pressure is your next priority",
        "Defense or weapon pressure matters more",
    ),
    "range": (
        "You need safer effective range",
        "Close-range pressure is already safe",
    ),
    "farming/tempo": (
        "You need faster lane and farm tempo",
        "The next fight needs immediate power",
    ),
}
_OPTIONAL_PURPOSE_PHRASES = (
    (
        "sustain",
        (
            "restore health",
            "health regen",
            "lifesteal",
            "life steal",
            "heal",
            "bonus health",
            "health max",
        ),
        "Sustain",
    ),
    (
        "ability uptime",
        ("cooldown", "recharge", "ability charges"),
        "Ability Uptime",
    ),
    (
        "mobility",
        (
            "dash",
            "teleport",
            "move speed",
            "movement speed",
            "sprint",
            "stamina",
        ),
        "Mobility",
    ),
    (
        "control/catch",
        ("stun", "silence", "root", "ground", "disarm", "movement slow"),
        "Control",
    ),
    ("melee", ("melee",), "Melee Power"),
    (
        "range",
        ("weapon range", "cast range", "attack range", "increase its range"),
        "Range",
    ),
    (
        "farming/tempo",
        ("bonus souls", "souls over time", "creep damage", "farm", "npcs"),
        "Farm Tempo",
    ),
    (
        "weapon pressure",
        (
            "weapon damage",
            "bullet damage",
            "fire rate",
            "ammo",
            "bullet velocity",
        ),
        "Weapon Pressure",
    ),
    ("Spirit pressure", ("spirit damage", "spirit power"), "Spirit Pressure"),
)


def _property_number(asset: dict[str, Any], name: str) -> float | None:
    properties = asset.get("properties")
    if not isinstance(properties, dict):
        return None
    prop = properties.get(name)
    if not isinstance(prop, dict):
        return None
    value = prop.get("value")
    if not isinstance(value, (str, int, float)):
        return None
    try:
        number = float(value)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def _channel_protection_decision(
    asset: dict[str, Any],
    hero_mechanics: dict[str, Any] | None,
) -> tuple[str, str, str] | None:
    if hero_mechanics is None:
        return None
    protection_duration = _property_number(asset, "AbilityDuration")
    abilities = hero_mechanics.get("abilities")
    if protection_duration is None or not isinstance(abilities, list):
        return None
    candidates: list[tuple[bool, int, int, str]] = []
    for ability in abilities:
        if not isinstance(ability, dict):
            continue
        channel_duration = _property_number(ability, "AbilityChannelTime")
        ability_id = ability.get("id")
        slot = ability.get("slot")
        name = clean_mechanical_text(ability.get("name"))
        if not isinstance(ability_id, int) or not isinstance(slot, int) or not name:
            continue
        if (
            channel_duration is None
            or channel_duration <= 0
            or channel_duration > protection_duration
        ):
            continue
        candidates.append((slot != 4, slot, ability_id, name))
    if not candidates:
        return None
    _, _, _, ability_name = min(candidates)
    return (
        f"Activate before {ability_name} when enemy control can interrupt it",
        "Control Immunity protects the channel",
        f"Enemy control cannot threaten {ability_name}",
    )


def optional_item_decision(
    asset: dict[str, Any],
    *,
    hero_mechanics: dict[str, Any] | None = None,
) -> tuple[str, str, str] | None:
    """Create controlled USE, WHY, and SKIP copy from material item mechanics.

    Returns:
        Three tactical fields, or ``None`` when no concrete purpose is present.

    """
    responses = _response_mechanic_labels(asset)
    if responses.get("hard_control"):
        channel_decision = _channel_protection_decision(asset, hero_mechanics)
        if channel_decision is not None:
            return channel_decision
    response_purposes = (
        ("healing", "anti-heal"),
        ("hard_control", "control defense"),
        ("slow_resistance", "control defense"),
        ("bullet_pressure", "bullet defense"),
        ("spirit_burst", "spirit defense"),
        ("ally_protection", "ally protection"),
        ("mobility_denial", "control/catch"),
    )
    for response, purpose in response_purposes:
        labels = responses.get(response)
        if labels:
            use, skip = _OPTIONAL_PURPOSE_COPY[purpose]
            return use, " and ".join(labels[:2]), skip
    text = canonical_mechanics_text(_optional_observed_mechanics(asset))
    for purpose, phrases, why in _OPTIONAL_PURPOSE_PHRASES:
        if any(phrase in text for phrase in phrases):
            use, skip = _OPTIONAL_PURPOSE_COPY[purpose]
            return use, why, skip
    return None


def canonical_mechanics_text(mechanics: dict[str, Any]) -> str:
    """Flatten normalized mechanics for conservative phrase classification.

    Returns:
        Case-folded canonical JSON text.

    """
    return json.dumps(
        mechanics,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).casefold()


def ability_definitions_from_kit(
    kit: dict[str, Any],
) -> dict[int, AbilityDefinition]:
    """Resolve signature abilities and explicit qualifiers from a kit record.

    Returns:
        Definitions whose first unlock consumes the next level-granted unlock token.

    Raises:
        MechanicsError: If the kit's four abilities are incomplete.

    """
    raw_abilities = kit.get("abilities")
    if not isinstance(raw_abilities, list) or len(raw_abilities) != 4:
        raise MechanicsError("kit must contain four signature abilities")
    definitions: dict[int, AbilityDefinition] = {}
    for raw in raw_abilities:
        if not isinstance(raw, dict) or not isinstance(raw.get("id"), int):
            raise MechanicsError("kit contains an invalid signature ability")
        ability_id = int(raw["id"])
        normalized = canonical_mechanics_text(raw)
        qualifiers = frozenset(
            qualifier
            for qualifier in ("charged", "channeled", "airborne")
            if qualifier in normalized
            or (
                qualifier == "channeled"
                and (_property_number(raw, "AbilityChannelTime") or 0) > 0
            )
        )
        raw_unlock_level = raw.get("unlock_level")
        unlock_level = (
            int(raw_unlock_level)
            if isinstance(raw_unlock_level, int) and raw_unlock_level > 0
            else 1
        )
        raw_upgrade_costs = raw.get("upgrade_costs")
        upgrade_costs = (
            tuple(int(cost) for cost in raw_upgrade_costs)
            if isinstance(raw_upgrade_costs, list)
            and raw_upgrade_costs
            and all(isinstance(cost, int) and cost > 0 for cost in raw_upgrade_costs)
            else DEFAULT_ABILITY_UPGRADE_COSTS
        )
        definitions[ability_id] = AbilityDefinition(
            ability_id,
            unlock_level=unlock_level,
            upgrade_costs=upgrade_costs,
            qualifiers=qualifiers,
            ultimate=int(raw.get("slot") or 0) == 4,
        )
    return definitions


@dataclass(frozen=True)
class ItemNode:
    item_id: int
    class_name: str
    name: str
    cost: int
    slot: str
    tier: int
    component_classes: tuple[str, ...]
    active: bool
    unique: bool
    max_count: int


class ItemGraph:
    """Validated directed acyclic graph of current item upgrades."""

    def __init__(self, nodes: dict[int, ItemNode]) -> None:
        if not nodes:
            raise MechanicsError("item graph is empty")
        self.nodes = dict(nodes)
        self.by_class = {node.class_name: node for node in nodes.values()}
        if len(self.by_class) != len(nodes):
            raise MechanicsError("item class names must be unique")
        self.components: dict[int, tuple[int, ...]] = {}
        children: dict[int, list[int]] = {item_id: [] for item_id in nodes}
        for node in nodes.values():
            resolved: list[int] = []
            for class_name in node.component_classes:
                component = self.by_class.get(class_name)
                if component is None:
                    raise MechanicsError(
                        f"item {node.name} references missing component {class_name}"
                    )
                resolved.append(component.item_id)
                children[component.item_id].append(node.item_id)
            self.components[node.item_id] = tuple(resolved)
        self.children = {
            item_id: tuple(sorted(item_children))
            for item_id, item_children in children.items()
        }
        self._validate_acyclic()

    @classmethod
    def from_assets(cls, assets: list[dict[str, Any]]) -> ItemGraph:
        nodes: dict[int, ItemNode] = {}
        for asset in assets:
            item_id = asset.get("id")
            class_name = asset.get("class_name")
            if (
                not isinstance(item_id, int)
                or not isinstance(class_name, str)
                or not asset.get("shopable")
                or asset.get("disabled")
            ):
                continue
            raw_components = asset.get("component_items") or []
            if not isinstance(raw_components, list) or not all(
                isinstance(component, str) for component in raw_components
            ):
                raise MechanicsError(f"item {item_id} has malformed components")
            max_count = asset.get("max_count")
            nodes[item_id] = ItemNode(
                item_id=item_id,
                class_name=class_name,
                name=str(asset.get("name") or class_name),
                cost=max(0, int(asset.get("cost") or 0)),
                slot=str(asset.get("item_slot_type") or "unknown").casefold(),
                tier=int(asset.get("item_tier") or 0),
                component_classes=tuple(raw_components),
                active=bool(asset.get("is_active_item")),
                unique=bool(asset.get("is_unique", True)),
                max_count=(max(1, int(max_count)) if isinstance(max_count, int) else 1),
            )
        return cls(nodes)

    def _validate_acyclic(self) -> None:
        visiting: set[int] = set()
        visited: set[int] = set()

        def visit(item_id: int) -> None:
            if item_id in visiting:
                raise MechanicsError("item component graph contains a cycle")
            if item_id in visited:
                return
            visiting.add(item_id)
            for component_id in self.components[item_id]:
                visit(component_id)
            visiting.remove(item_id)
            visited.add(item_id)

        for item_id in self.nodes:
            visit(item_id)

    def transitive_components(self, item_id: int) -> tuple[int, ...]:
        """Return every component ancestor once in dependency order.

        Returns:
            Component item IDs, with nested components before their parents.

        """
        self.require(item_id)
        ordered: list[int] = []
        seen: set[int] = set()

        def collect(current: int) -> None:
            for component_id in self.components[current]:
                collect(component_id)
                if component_id not in seen:
                    seen.add(component_id)
                    ordered.append(component_id)

        collect(item_id)
        return tuple(ordered)

    def require(self, item_id: int) -> ItemNode:
        """Resolve one current item.

        Returns:
            The item node.

        Raises:
            MechanicsError: If the item does not exist in the snapshot.

        """
        try:
            return self.nodes[item_id]
        except KeyError as error:
            raise MechanicsError(f"unknown current item {item_id}") from error

    def credited_component_value(
        self,
        item_id: int,
        owned: tuple[int, ...],
    ) -> int:
        """Calculate consumed owned component catalog value.

        Returns:
            Value credited by direct owned components of the child.

        """
        owned_set = set(owned)
        return sum(
            self.nodes[component_id].cost
            for component_id in self.components[self.require(item_id).item_id]
            if component_id in owned_set
        )

    def incremental_cash_cost(self, item_id: int, owned: tuple[int, ...]) -> int:
        """Calculate current child price less credited owned components.

        Returns:
            Non-negative liquid currency required for the purchase.

        """
        node = self.require(item_id)
        return max(0, node.cost - self.credited_component_value(item_id, owned))

    def total_tree_investment(self, item_id: int) -> int:
        """Return the catalog investment represented by an upgrade tree.

        Returns:
            Root price, which includes the credited component value in current assets.

        """
        return self.require(item_id).cost


@dataclass(frozen=True)
class CategoryBonus:
    threshold: int
    values: dict[str, Any]


@dataclass(frozen=True)
class CategoryBonusTable:
    categories: dict[str, tuple[CategoryBonus, ...]]

    @classmethod
    def from_asset(cls, asset: dict[str, Any]) -> CategoryBonusTable:
        raw = asset.get("cost_bonuses")
        if not isinstance(raw, dict):
            raise MechanicsError("authoritative cost_bonuses are missing")
        categories: dict[str, tuple[CategoryBonus, ...]] = {}
        for category, rows in raw.items():
            categories[str(category).casefold()] = _category_bonuses(category, rows)
        return cls(categories)

    def crossed(
        self,
        category: str,
        previous_spend: int,
        new_spend: int,
    ) -> tuple[CategoryBonus, ...]:
        """Return breakpoints crossed once by a monotone spend transition.

        Returns:
            Bonuses whose threshold lies after previous and at/before new spend.

        Raises:
            MechanicsError: If cumulative spend moves backwards.

        """
        if new_spend < previous_spend:
            raise MechanicsError("category spend cannot move backwards")
        return tuple(
            bonus
            for bonus in self.categories.get(category.casefold(), ())
            if previous_spend < bonus.threshold <= new_spend
        )


def _category_bonus_rows(category: object, rows: object) -> list[object]:
    if isinstance(rows, dict):
        return [
            {"threshold": threshold, "value": value}
            for threshold, value in rows.items()
        ]
    if not isinstance(rows, list):
        raise MechanicsError(f"malformed {category} cost bonuses")
    return cast("list[object]", rows)


def _category_bonus(category: object, row: object) -> CategoryBonus:
    if not isinstance(row, dict):
        raise MechanicsError(f"malformed {category} cost bonus")
    threshold = row.get("gold_threshold", row.get("threshold", row.get("cost")))
    if isinstance(threshold, str) and threshold.isdigit():
        threshold = int(threshold)
    if not isinstance(threshold, int) or threshold < 0:
        raise MechanicsError(f"invalid {category} bonus threshold")
    return CategoryBonus(
        threshold,
        normalize_mechanical_value({
            key: value
            for key, value in row.items()
            if key not in {"gold_threshold", "threshold", "cost"}
        }),
    )


def _category_bonuses(category: object, rows: object) -> tuple[CategoryBonus, ...]:
    ordered = sorted(
        (
            _category_bonus(category, row)
            for row in _category_bonus_rows(category, rows)
        ),
        key=lambda bonus: bonus.threshold,
    )
    if len({bonus.threshold for bonus in ordered}) != len(ordered):
        raise MechanicsError(f"duplicate {category} bonus threshold")
    return tuple(ordered)


@dataclass(frozen=True)
class AbilityDefinition:
    ability_id: int
    unlock_level: int
    upgrade_costs: tuple[int, ...] = DEFAULT_ABILITY_UPGRADE_COSTS
    qualifiers: frozenset[str] = frozenset()
    ultimate: bool = False


@dataclass(frozen=True)
class AbilityAction:
    level: int
    ability_id: int


@dataclass(frozen=True)
class AbilityTimelineStep:
    level: int
    ability_id: int
    rank: int
    cost: int
    currency: str
    ap_remaining: int
    unlocks_remaining: int


def _level_rows(level_info: object) -> list[tuple[object, object]]:
    if isinstance(level_info, dict):
        return list(level_info.items())
    if isinstance(level_info, list):
        return [
            (row.get("level"), row) if isinstance(row, dict) else (None, row)
            for row in level_info
        ]
    raise MechanicsError("hero level_info must be an object or list")


def _level_grant(raw_level: object, row: object) -> tuple[int, tuple[int, int]]:
    if not isinstance(row, dict):
        raise MechanicsError("level_info row is missing level")
    level = raw_level
    if isinstance(level, str) and level.isdigit():
        level = int(level)
    if not isinstance(level, int):
        raise MechanicsError("level_info row is missing level")
    currencies = row.get("bonus_currencies", [])
    if not isinstance(currencies, list) or not all(
        isinstance(currency, str) for currency in currencies
    ):
        raise MechanicsError("level_info has malformed bonus currencies")
    explicit_ap = row.get("ability_points", row.get("ability_points_granted", 0))
    explicit_unlocks = row.get("ability_unlocks", 0)
    if (
        not isinstance(explicit_ap, int)
        or explicit_ap < 0
        or not isinstance(explicit_unlocks, int)
        or explicit_unlocks < 0
    ):
        raise MechanicsError("level_info has an invalid ability-point grant")
    ap = explicit_ap + sum(currency == "EAbilityPoints" for currency in currencies)
    unlocks = explicit_unlocks + sum(
        currency == "EAbilityUnlocks" for currency in currencies
    )
    return level, (unlocks, ap)


def _currency_grants_by_level(level_info: object) -> dict[int, tuple[int, int]]:
    result: dict[int, tuple[int, int]] = {}
    for raw_level, row in _level_rows(level_info):
        level, grant = _level_grant(raw_level, row)
        result[level] = grant
    if not result:
        raise MechanicsError("level_info contains no levels")
    return result


@dataclass
class _AbilityProgress:
    ranks: dict[int, int]
    ap: int = 0
    unlocks: int = 0
    current_level: int = 0


def _advance_ability_level(
    progress: _AbilityProgress,
    grants: dict[int, tuple[int, int]],
    level: int,
) -> None:
    for current in range(progress.current_level + 1, level + 1):
        unlock_grant, ap_grant = grants.get(current, (0, 0))
        progress.unlocks += unlock_grant
        progress.ap += ap_grant
    progress.current_level = level


def _apply_ability_action(
    progress: _AbilityProgress,
    definitions: dict[int, AbilityDefinition],
    action: AbilityAction,
) -> AbilityTimelineStep:
    definition = definitions.get(action.ability_id)
    if definition is None:
        raise MechanicsError(f"unknown ability {action.ability_id}")
    prior_rank = progress.ranks[action.ability_id]
    if prior_rank == 0:
        if action.level < definition.unlock_level:
            raise MechanicsError(
                f"ability {action.ability_id} unlocks at level {definition.unlock_level}"
            )
        cost = 1
        currency = "ability_unlock"
        if not progress.unlocks:
            raise MechanicsError(
                f"ability {action.ability_id} needs an unlock currency"
            )
        progress.unlocks -= 1
    else:
        cost_index = prior_rank - 1
        if cost_index >= len(definition.upgrade_costs):
            raise MechanicsError(f"ability {action.ability_id} is already maxed")
        cost = definition.upgrade_costs[cost_index]
        currency = "ability_points"
        if cost > progress.ap:
            raise MechanicsError(
                f"ability {action.ability_id} costs {cost} AP with only {progress.ap} available"
            )
        progress.ap -= cost
    progress.ranks[action.ability_id] = prior_rank + 1
    return AbilityTimelineStep(
        level=action.level,
        ability_id=action.ability_id,
        rank=prior_rank + 1,
        cost=cost,
        currency=currency,
        ap_remaining=progress.ap,
        unlocks_remaining=progress.unlocks,
    )


def validate_ability_timeline(
    definitions: dict[int, AbilityDefinition],
    level_info: object,
    actions: tuple[AbilityAction, ...],
) -> tuple[AbilityTimelineStep, ...]:
    """Simulate unlocks/upgrades against pinned levels and AP grants.

    Returns:
        Legal actions with exact AP balances.

    Raises:
        MechanicsError: If an action is unknown, too early, over-upgraded, or unaffordable.

    """
    grants = _currency_grants_by_level(level_info)
    if tuple(actions) != tuple(sorted(actions, key=lambda action: action.level)):
        raise MechanicsError("ability actions must be ordered by level")
    progress = _AbilityProgress(dict.fromkeys(definitions, 0))
    result: list[AbilityTimelineStep] = []
    for action in actions:
        if action.level not in grants:
            raise MechanicsError(f"ability action uses unknown level {action.level}")
        _advance_ability_level(progress, grants, action.level)
        result.append(_apply_ability_action(progress, definitions, action))
    return tuple(result)


def schedule_ability_path(
    definitions: dict[int, AbilityDefinition],
    level_info: object,
    ability_ids: tuple[int, ...],
) -> tuple[AbilityAction, ...]:
    """Place an observed upgrade sequence at its earliest legal pinned levels.

    Returns:
        Nondecreasing level actions that consume the real unlock/AP currencies.

    Raises:
        MechanicsError: If no current level can realize an observed action.

    """
    levels = tuple(sorted(_currency_grants_by_level(level_info)))
    if not levels:
        raise MechanicsError("cannot schedule abilities without current levels")
    actions: list[AbilityAction] = []
    minimum_level = levels[0]
    for ability_id in ability_ids:
        scheduled = False
        for level in levels:
            if level < minimum_level:
                continue
            candidate = (*actions, AbilityAction(level, ability_id))
            try:
                validate_ability_timeline(definitions, level_info, candidate)
            except MechanicsError:
                continue
            actions.append(AbilityAction(level, ability_id))
            minimum_level = level
            scheduled = True
            break
        if not scheduled:
            raise MechanicsError(
                f"ability path cannot legally schedule ability {ability_id}"
            )
    return tuple(actions)


@dataclass(frozen=True)
class InventoryState:
    owned: tuple[int, ...] = ()
    unlocked_flex_slots: int = 0

    def __post_init__(self) -> None:
        """Validate the flex-slot domain.

        Raises:
            MechanicsError: If the state claims an impossible flex count.

        """
        if not 0 <= self.unlocked_flex_slots <= MAX_FLEX_SLOTS:
            raise MechanicsError("unlocked flex slots must be between zero and three")


def purchase_item(
    graph: ItemGraph,
    state: InventoryState,
    item_id: int,
    *,
    required_flex_slots: int = 0,
) -> InventoryState:
    """Apply one legal purchase including direct component consumption.

    Returns:
        The post-purchase inventory.

    Raises:
        MechanicsError: If availability, duplicate, flex, slot, or active limits fail.

    """
    node = graph.require(item_id)
    if required_flex_slots > state.unlocked_flex_slots:
        raise MechanicsError("purchase requires unavailable flex capacity")
    owned = list(state.owned)
    count = owned.count(item_id)
    if (node.unique and count) or count >= node.max_count:
        raise MechanicsError(f"item {node.name} exceeds its ownership limit")
    for component_id in graph.components[item_id]:
        if component_id in owned:
            owned.remove(component_id)
    owned.append(item_id)
    capacity = BASE_INVENTORY_SLOTS + state.unlocked_flex_slots
    if len(owned) > capacity:
        raise MechanicsError(f"purchase exceeds {capacity} available item slots")
    active_count = sum(graph.require(owned_id).active for owned_id in owned)
    if active_count > MAX_ACTIVE_ITEMS:
        raise MechanicsError("purchase exceeds four active-item bindings")
    return InventoryState(tuple(owned), state.unlocked_flex_slots)


@dataclass(frozen=True)
class _ComponentPlan:
    item_ids: tuple[int, ...]
    dependencies: tuple[frozenset[int], ...]


class _ComponentPlanner:
    def __init__(self, graph: ItemGraph) -> None:
        self.graph = graph
        self.planned_ids: list[int] = []
        self.dependencies: list[set[int]] = []
        self.consumed_by: dict[int, int] = {}
        self.owned_actions: dict[int, int] = {}
        self.last_action_by_item: dict[int, int] = {}
        self.state = InventoryState()

    def plan(self, item_id: int) -> int:
        if item_id in self.state.owned:
            try:
                return self.owned_actions[item_id]
            except KeyError as error:
                raise MechanicsError(
                    f"owned item {item_id} has no planned purchase action"
                ) from error

        component_actions = tuple(
            self.plan(component_id) for component_id in self.graph.components[item_id]
        )
        action_index = len(self.planned_ids)
        action_dependencies = set(component_actions)
        previous_action = self.last_action_by_item.get(item_id)
        if previous_action is not None:
            consumer = self.consumed_by.get(previous_action)
            if consumer is None:
                raise MechanicsError(
                    f"item {item_id} cannot be rebought before its prior copy is consumed"
                )
            action_dependencies.add(consumer)

        missing = [
            component_id
            for component_id in self.graph.components[item_id]
            if component_id not in self.state.owned
        ]
        if missing:
            raise MechanicsError(
                f"planned item {item_id} is missing components {missing}"
            )
        self.state = purchase_item(self.graph, self.state, item_id)
        self.planned_ids.append(item_id)
        self.dependencies.append(action_dependencies)
        for component_id, component_action in zip(
            self.graph.components[item_id], component_actions, strict=True
        ):
            self.consumed_by[component_action] = action_index
            self.owned_actions.pop(component_id, None)
        self.owned_actions[item_id] = action_index
        self.last_action_by_item[item_id] = action_index
        return action_index

    def build(self, target_ids: tuple[int, ...]) -> _ComponentPlan:
        final_actions: list[int] = []
        for item_id in target_ids:
            action_index = self.plan(item_id)
            if action_index in final_actions:
                raise MechanicsError(f"final item {item_id} was already scheduled")
            if final_actions:
                self.dependencies[action_index].add(final_actions[-1])
            final_actions.append(action_index)
        if set(self.state.owned) != set(target_ids):
            raise MechanicsError(
                "planned component path does not end in final inventory"
            )
        return _ComponentPlan(
            tuple(self.planned_ids),
            tuple(frozenset(required) for required in self.dependencies),
        )


def _plan_component_actions(
    graph: ItemGraph, target_ids: tuple[int, ...]
) -> _ComponentPlan:
    return _ComponentPlanner(graph).build(target_ids)


class _ComponentScheduleSearch:
    def __init__(
        self,
        graph: ItemGraph,
        plan: _ComponentPlan,
        target_ids: tuple[int, ...],
        priorities: Mapping[int, tuple[float, float, int]],
    ) -> None:
        self.graph = graph
        self.plan = plan
        self.target_ids = target_ids
        self.priorities = priorities
        self.failed_states: set[tuple[frozenset[int], tuple[int, ...], int]] = set()

    def _ready_actions(self, completed: frozenset[int]) -> list[int]:
        return sorted(
            (
                index
                for index, required in enumerate(self.plan.dependencies)
                if index not in completed and required <= completed
            ),
            key=lambda index: (
                *self.priorities.get(
                    self.plan.item_ids[index],
                    (
                        float("inf"),
                        float("inf"),
                        self.plan.item_ids[index],
                    ),
                ),
                index,
            ),
        )

    def search(
        self,
        completed: frozenset[int],
        state: InventoryState,
    ) -> tuple[int, ...] | None:
        if len(completed) == len(self.plan.item_ids):
            return () if set(state.owned) == set(self.target_ids) else None
        state_key = (
            completed,
            tuple(sorted(state.owned)),
            state.unlocked_flex_slots,
        )
        if state_key in self.failed_states:
            return None
        for action_index in self._ready_actions(completed):
            item_id = self.plan.item_ids[action_index]
            if any(
                component_id not in state.owned
                for component_id in self.graph.components[item_id]
            ):
                continue
            try:
                next_state = purchase_item(self.graph, state, item_id)
            except MechanicsError:
                continue
            suffix = self.search(completed | {action_index}, next_state)
            if suffix is not None:
                return (action_index, *suffix)
        self.failed_states.add(state_key)
        return None


def _search_component_schedule(
    graph: ItemGraph,
    plan: _ComponentPlan,
    target_ids: tuple[int, ...],
    priorities: Mapping[int, tuple[float, float, int]],
) -> tuple[int, ...] | None:
    return _ComponentScheduleSearch(graph, plan, target_ids, priorities).search(
        frozenset(), InventoryState()
    )


def schedule_component_path(
    graph: ItemGraph,
    targets: Sequence[int],
    priorities: Mapping[int, tuple[float, float, int]],
) -> tuple[int, ...]:
    """Schedule a chronological, legal purchase path for a final inventory.

    Purchase timing ranks every action, while component dependencies, final-item
    order, inventory capacity, active-item limits, and consumed-component rebuys
    remain hard constraints.

    Returns:
        Item IDs in executable left-to-right purchase order.

    Raises:
        MechanicsError: If no legal schedule reaches the requested inventory.

    """
    target_ids = tuple(targets)
    if not target_ids:
        raise MechanicsError("component schedule has no final inventory targets")
    if len(set(target_ids)) != len(target_ids):
        raise MechanicsError("component schedule final inventory contains duplicates")
    for item_id in target_ids:
        graph.require(item_id)

    plan = _plan_component_actions(graph, target_ids)
    scheduled_actions = _search_component_schedule(graph, plan, target_ids, priorities)
    if scheduled_actions is None:
        names = ", ".join(graph.require(item_id).name for item_id in target_ids)
        raise MechanicsError(f"no legal chronological component schedule for {names}")
    return tuple(plan.item_ids[index] for index in scheduled_actions)


def sell_item(graph: ItemGraph, state: InventoryState, item_id: int) -> InventoryState:
    """Sell one currently owned item.

    Returns:
        The post-sale inventory.

    Raises:
        MechanicsError: If the item is unknown or not owned.

    """
    graph.require(item_id)
    owned = list(state.owned)
    if item_id not in owned:
        raise MechanicsError(f"cannot sell unowned item {item_id}")
    owned.remove(item_id)
    return InventoryState(tuple(owned), state.unlocked_flex_slots)


def validate_imbue(
    definitions: dict[int, AbilityDefinition],
    learned_abilities: set[int],
    ability_id: int,
    *,
    required_qualifier: str | None = None,
    allow_ultimate: bool = True,
) -> None:
    """Validate an item-to-ability imbue against current learned mechanics.

    Raises:
        MechanicsError: If the target is unlearned, disallowed, or unqualified.

    """
    definition = definitions.get(ability_id)
    if definition is None or ability_id not in learned_abilities:
        raise MechanicsError("imbue target must be a current learned ability")
    if definition.ultimate and not allow_ultimate:
        raise MechanicsError("this item cannot imbue an ultimate ability")
    if required_qualifier and required_qualifier not in definition.qualifiers:
        raise MechanicsError(f"ability {ability_id} is not proven {required_qualifier}")
