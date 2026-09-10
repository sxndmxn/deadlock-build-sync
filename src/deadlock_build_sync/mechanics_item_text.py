from __future__ import annotations

import json
import re

from .mechanics_assets import (
    _is_populated,
    clean_mechanical_text,
    extract_asset_mechanics,
    normalize_mechanical_value,
)
from .value_validation import object_dict

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


def _extract_active_property_mechanics(
    asset: dict[str, object],
) -> dict[str, dict[str, object]]:
    raw_properties = object_dict(asset.get("properties"))
    if raw_properties is None:
        return {}
    active: dict[str, dict[str, object]] = {}
    for name, raw_property in raw_properties.items():
        prop = object_dict(raw_property)
        if prop is None or "value" not in prop:
            continue
        value = prop["value"]
        disabled_value = prop.get("disable_value")
        if disabled_value is not None and str(value) == str(disabled_value):
            continue
        if value is None or (
            isinstance(value, (str, int, float)) and str(value) in {"", "0", "0.0"}
        ):
            continue
        active[str(name)] = {
            key: prop[key]
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
            if key in prop
        }
    return active


def _extract_base_description(asset: dict[str, object]) -> object:
    description = asset.get("description")
    description_object = object_dict(description)
    if description_object is not None:
        return {
            key: description_object[key]
            for key in ("desc", "passive", "active")
            if _is_populated(description_object.get(key))
        }
    return description


def _extract_important_property_mechanics(
    asset: dict[str, object],
) -> dict[str, dict[str, object]]:
    return {
        name: value
        for name, value in _extract_active_property_mechanics(asset).items()
        if value.get("tooltip_is_important") is True
    }


def _is_resistance_reduction_property(name: str, value: dict[str, object]) -> bool:
    identity = " ".join((
        name,
        str(value.get("label") or ""),
        str(value.get("provided_property_type") or ""),
    )).casefold()
    return "resist" in identity and (
        "reduction" in identity or str(value.get("value") or "").startswith("-")
    )


def _extract_response_property_mechanics(
    asset: dict[str, object],
) -> dict[str, dict[str, object]]:
    return {
        name: value
        for name, value in _extract_important_property_mechanics(asset).items()
        if not _is_resistance_reduction_property(name, value)
    }


def _extract_observed_mechanics(asset: dict[str, object]) -> dict[str, object]:
    mechanics = extract_asset_mechanics(asset)
    observed: dict[str, object] = {}
    description = _extract_base_description(asset)
    if _is_populated(description):
        observed["description"] = normalize_mechanical_value(description)
    for key in ("behaviour", "damage_type", "targeting", "weapon_info"):
        if key in mechanics:
            observed[key] = mechanics[key]
    important_properties = _extract_response_property_mechanics(asset)
    if important_properties:
        observed["properties"] = normalize_mechanical_value(important_properties)
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
            re.match(r"\s+(?:immunity|resistance)\b", suffix)
            if phrase == "movement slow"
            else None
        )
        if defensive_prefix is None and defensive_suffix is None:
            return True
        start = index + len(phrase)
    return False


def _classify_important_property_labels(
    asset: dict[str, object],
) -> dict[str, tuple[str, ...]]:
    labels: dict[str, list[str]] = {}
    for prop in _extract_response_property_mechanics(asset).values():
        property_type = str(prop.get("provided_property_type") or "").upper()
        label = clean_mechanical_text(prop.get("label"))
        normalized = serialize_mechanics_text(prop)
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


def _classify_response_mechanic_labels(
    asset: dict[str, object],
) -> dict[str, tuple[str, ...]]:
    text = serialize_mechanics_text(_extract_observed_mechanics(asset))
    labels = {
        key: list(value)
        for key, value in _classify_important_property_labels(asset).items()
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


def classify_observed_item_threats(asset: dict[str, object]) -> frozenset[str]:
    """Classify only explicit threat mechanics on an observed enemy item.

    Returns:
        Conservative threat labels supported by the pinned item text.

    """
    normalized = serialize_mechanics_text(_extract_observed_mechanics(asset))
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


def serialize_mechanics_text(mechanics: dict[str, object]) -> str:
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
