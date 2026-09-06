"""Describe optional needs from primary effects, never incidental bonus stats."""

from __future__ import annotations

import re

from .mechanics_assets import clean_mechanical_text
from .purchase_effect_rules import CONDITION_RULES, EFFECT_RULES, STAT_RULES
from .purchase_guidance_types import ItemPurpose
from .value_validation import object_dict, object_list, object_rows


def description_text(value: object) -> str:
    document = object_dict(value)
    if document is not None:
        return " ".join(description_text(document[key]) for key in sorted(document))
    rows = object_list(value)
    if rows is not None:
        return " ".join(description_text(part) for part in rows)
    return clean_mechanical_text(str(value)) if value is not None else ""


def primary_text(asset: dict[str, object]) -> str:
    parts = [description_text(asset.get("description"))]
    parts.extend(
        description_text(row.get("loc_string"))
        for section in object_rows(asset.get("tooltip_sections")) or []
        if section.get("section_type") != "innate"
        for row in object_rows(section.get("section_attributes")) or []
        if row.get("loc_string")
    )
    return " ".join(dict.fromkeys(part for part in parts if part)).strip()


def material_stats(asset: dict[str, object]) -> set[str]:
    keys = {
        key
        for section in object_rows(asset.get("tooltip_sections")) or []
        for row in object_rows(section.get("section_attributes")) or []
        for field in ("important_properties", "elevated_properties")
        for key in object_list(row.get(field)) or []
        if isinstance(key, str)
    }
    properties = object_dict(asset.get("properties")) or {}
    return {
        key
        for key in keys
        if str((object_dict(properties.get(key)) or {}).get("value", "0"))
        not in {"None", "0", "0.0", "-1", ""}
    }


def purpose(asset: dict[str, object]) -> ItemPurpose:
    text = primary_text(asset)
    normalized = re.sub(r"\s+([,.])", r"\1", text).casefold()
    for pattern, label, trigger in EFFECT_RULES:
        match = re.search(pattern, normalized)
        if match:
            resolved = next(
                (
                    value
                    for condition, value in CONDITION_RULES
                    if re.search(condition, normalized)
                ),
                trigger,
            )
            return ItemPurpose(label, resolved, match.group(), "primary effect text")
    if not text:
        stats = material_stats(asset)
        for keys, label, trigger in STAT_RULES:
            matched = sorted(stats.intersection(keys))
            if matched:
                return ItemPurpose(
                    label, trigger, ", ".join(matched), "material tooltip property"
                )
    return ItemPurpose(
        "General utility",
        text or "Main effect is unknown; follow the core",
        text,
        "unclassified",
    )
