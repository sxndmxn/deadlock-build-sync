from __future__ import annotations

import math

from .mechanics_assets import clean_mechanical_text
from .mechanics_item_text import (
    _optional_observed_mechanics,
    _response_mechanic_labels,
    canonical_mechanics_text,
)
from .value_validation import object_rows

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


def _property_number(asset: dict[str, object], name: str) -> float | None:
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
    asset: dict[str, object],
    hero_mechanics: dict[str, object] | None,
) -> tuple[str, str, str] | None:
    if hero_mechanics is None:
        return None
    protection_duration = _property_number(asset, "AbilityDuration")
    abilities = object_rows(hero_mechanics.get("abilities"))
    if protection_duration is None or abilities is None:
        return None
    candidates: list[tuple[bool, int, int, str]] = []
    for ability in abilities:
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
    asset: dict[str, object],
    *,
    hero_mechanics: dict[str, object] | None = None,
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
