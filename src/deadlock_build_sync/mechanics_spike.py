"""Mechanics-first power spike line for item hovers."""

from __future__ import annotations

from .mechanics_assets import clean_mechanical_text
from .mechanics_item_text import (
    _active_property_mechanics,
    _important_property_mechanics,
)
from .value_validation import object_dict, object_rows

_SPIRIT_PROPERTY_TYPE = "MODIFIER_VALUE_TECH_POWER"
_SPIRIT_SCALE_TYPE = "ETechPower"
_SPIRIT_SCALE_CLASS = "scale_function_tech_damage"
_SPIRIT_SLOT = "spirit"
_CONDITIONAL_GRANT_WORDS = ("imbued", "gain", "ambush", "reduction")
_MINIMUM_OFF_SLOT_SPIRIT = 30.0
_SEPARATOR = " · "


def _grant_value(name: str, prop: dict[str, object]) -> float | None:
    if prop.get("provided_property_type") != _SPIRIT_PROPERTY_TYPE:
        return None
    if any(word in name.casefold() for word in _CONDITIONAL_GRANT_WORDS):
        return None
    value = prop.get("value")
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except ValueError:
        return None
    return number if number > 0 else None


def _spirit_grant(asset: dict[str, object]) -> float | None:
    """Return the largest unconditional positive spirit grant the item provides.

    Returns:
        The grant an ability can scale with, or ``None`` when the item provides no
        such stat or provides it only conditionally.

    """
    grants = [
        grant
        for name, prop in _important_property_mechanics(asset).items()
        if (grant := _grant_value(name, prop)) is not None
    ]
    if not grants:
        return None
    return max(grants)


def _bought_for_spirit(asset: dict[str, object], grant: float) -> bool:
    return (
        asset.get("item_slot_type") == _SPIRIT_SLOT or grant >= _MINIMUM_OFF_SLOT_SPIRIT
    )


def _scales_with_spirit(scale: dict[str, object]) -> bool:
    return (
        scale.get("specific_stat_scale_type") == _SPIRIT_SCALE_TYPE
        or scale.get("class_name") == _SPIRIT_SCALE_CLASS
    )


def _ability_coefficient(ability: dict[str, object]) -> float | None:
    raw_properties = object_dict(ability.get("properties")) or {}
    best: float | None = None
    for name in _active_property_mechanics(ability):
        prop = object_dict(raw_properties.get(name))
        scale = object_dict(prop.get("scale_function")) if prop is not None else None
        if scale is None or not _scales_with_spirit(scale):
            continue
        stat_scale = scale.get("stat_scale")
        coefficient = (
            float(stat_scale)
            if isinstance(stat_scale, (int, float)) and not isinstance(stat_scale, bool)
            else 0.0
        )
        if best is None or coefficient > best:
            best = coefficient
    return best


def _candidates(hero_mechanics: dict[str, object]) -> list[tuple[float, int, str]]:
    candidates: list[tuple[float, int, str]] = []
    for ability in object_rows(hero_mechanics.get("abilities")) or ():
        slot = ability.get("slot")
        name = clean_mechanical_text(ability.get("name"))
        if not isinstance(slot, int) or not name:
            continue
        coefficient = _ability_coefficient(ability)
        if coefficient is None:
            continue
        candidates.append((-coefficient, slot, name))
    return sorted(candidates)


def _spike_phrase(candidate: tuple[float, int, str]) -> str:
    negative_coefficient, _, name = candidate
    coefficient = round(-negative_coefficient, 2)
    suffix = f" x{coefficient:g}" if coefficient > 0 else ""
    return f"{name} spirit{suffix}"


def power_spike_text(
    asset: dict[str, object],
    hero_mechanics: dict[str, object] | None,
    *,
    max_chars: int,
) -> str:
    """Name up to two abilities that scale with an item's spirit power grant.

    Returns:
        A short phrase such as ``Napalm spirit x0.6``, or an empty string when the
        item is not bought for its spirit, grants it only conditionally, or no
        phrase fits within ``max_chars``.

    """
    if hero_mechanics is None:
        return ""
    grant = _spirit_grant(asset)
    if grant is None or not _bought_for_spirit(asset, grant):
        return ""
    candidates = _candidates(hero_mechanics)
    for count in (2, 1):
        selected = candidates[:count]
        if not selected:
            return ""
        text = _SEPARATOR.join(_spike_phrase(candidate) for candidate in selected)
        if len(text) <= max_chars:
            return text
    return ""
