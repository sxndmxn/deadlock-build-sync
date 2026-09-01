"""Mechanics-first power spike line for item hovers."""

from __future__ import annotations

from .mechanics_assets import clean_mechanical_text
from .mechanics_item_text import (
    _active_property_mechanics,
    _important_property_mechanics,
)
from .value_validation import object_dict, object_list, object_rows

_ITEM_CHANNELS = {
    "MODIFIER_VALUE_TECH_POWER": "spirit",
    "MODIFIER_VALUE_COOLDOWN_REDUCTION_PERCENTAGE": "cooldown",
    "MODIFIER_VALUE_BONUS_ABILITY_DURATION_PERCENTAGE": "duration",
    "MODIFIER_VALUE_TECH_RANGE_PERCENT": "range",
    "MODIFIER_VALUE_TECH_RADIUS_PERCENT": "radius",
}
_CHANNEL_ORDER = tuple(dict.fromkeys(_ITEM_CHANNELS.values()))
_CHANNEL_SCALE_TYPES = {
    "cooldown": "ETechCooldown",
    "duration": "ETechDuration",
    "range": "ETechRange",
    "radius": "ETechRadius",
}
_SPIRIT_SCALE_TYPE = "ETechPower"
_SPIRIT_SCALE_CLASS = "scale_function_tech_damage"
_SEPARATOR = " · "


def _item_channels(asset: dict[str, object]) -> frozenset[str]:
    return frozenset(
        _ITEM_CHANNELS[str(prop.get("provided_property_type"))]
        for prop in _important_property_mechanics(asset).values()
        if str(prop.get("provided_property_type")) in _ITEM_CHANNELS
    )


def _scale_channels(scale: dict[str, object]) -> list[tuple[str, float]]:
    scale_type = scale.get("specific_stat_scale_type")
    scaling_stats = {
        str(stat) for stat in object_list(scale.get("scaling_stats")) or ()
    }
    matches: list[tuple[str, float]] = []
    if (
        scale_type == _SPIRIT_SCALE_TYPE
        or scale.get("class_name") == _SPIRIT_SCALE_CLASS
    ):
        stat_scale = scale.get("stat_scale")
        coefficient = (
            float(stat_scale)
            if isinstance(stat_scale, (int, float)) and not isinstance(stat_scale, bool)
            else 0.0
        )
        matches.append(("spirit", coefficient))
    matches.extend(
        (channel, 0.0)
        for channel, expected in _CHANNEL_SCALE_TYPES.items()
        if scale_type == expected or expected in scaling_stats
    )
    return matches


def _ability_channel(
    ability: dict[str, object],
    channels: frozenset[str],
) -> tuple[float, str] | None:
    raw_properties = object_dict(ability.get("properties")) or {}
    best: tuple[float, int, str] | None = None
    for name in _active_property_mechanics(ability):
        prop = object_dict(raw_properties.get(name))
        scale = object_dict(prop.get("scale_function")) if prop is not None else None
        if scale is None:
            continue
        for channel, coefficient in _scale_channels(scale):
            if channel not in channels:
                continue
            candidate = (-coefficient, _CHANNEL_ORDER.index(channel), channel)
            if best is None or candidate < best:
                best = candidate
    if best is None:
        return None
    return -best[0], best[2]


def _candidates(
    hero_mechanics: dict[str, object],
    channels: frozenset[str],
) -> list[tuple[float, int, str, str]]:
    candidates: list[tuple[float, int, str, str]] = []
    for ability in object_rows(hero_mechanics.get("abilities")) or ():
        slot = ability.get("slot")
        name = clean_mechanical_text(ability.get("name"))
        if not isinstance(slot, int) or not name:
            continue
        match = _ability_channel(ability, channels)
        if match is None:
            continue
        coefficient, channel = match
        candidates.append((-coefficient, slot, name, channel))
    return sorted(candidates)


def _spike_phrase(candidate: tuple[float, int, str, str]) -> str:
    negative_coefficient, _, name, channel = candidate
    coefficient = round(-negative_coefficient, 2)
    suffix = f" x{coefficient:g}" if coefficient > 0 else ""
    return f"{name} {channel}{suffix}"


def power_spike_text(
    asset: dict[str, object],
    hero_mechanics: dict[str, object] | None,
    *,
    max_chars: int,
) -> str:
    """Name up to two abilities whose scaling consumes an important item stat.

    Returns:
        A short phrase such as ``Napalm spirit x0.6``, or an empty string when no
        ability scales with the item or no phrase fits within ``max_chars``.

    """
    if hero_mechanics is None:
        return ""
    channels = _item_channels(asset)
    if not channels:
        return ""
    candidates = _candidates(hero_mechanics, channels)
    for count in (2, 1):
        selected = candidates[:count]
        if not selected:
            return ""
        text = _SEPARATOR.join(_spike_phrase(candidate) for candidate in selected)
        if len(text) <= max_chars:
            return text
    return ""
