"""Describe beam evidence and ability instructions."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from .build_support import numeric
from .value_validation import integer, object_dict, object_list, object_rows

if TYPE_CHECKING:
    from .purchase_types import PurchaseGuide

STATE_LABELS = {0: "Behind", 1: "Even", 2: "Ahead"}


def generator_metadata(guide: PurchaseGuide) -> dict[str, object]:
    return object_dict(guide.evidence_summary.get("generator")) or {}


def attach_beam_ability_names(
    guide: PurchaseGuide, kit: dict[str, object]
) -> PurchaseGuide:
    if not generator_metadata(guide):
        return guide
    return replace(
        guide,
        evidence_summary={
            **guide.evidence_summary,
            "ability_names": {
                str(row["id"]): str(row["name"])
                for row in object_rows(kit.get("abilities")) or []
            },
        },
    )


def _variant_state_rows(guide: PurchaseGuide) -> list[tuple[str, dict[str, object]]]:
    metadata = generator_metadata(guide)
    states = object_list(metadata.get("states")) or []
    evidence = object_dict(metadata.get("state_evidence")) or {}
    rows = []
    for state, label in STATE_LABELS.items():
        if state not in states:
            continue
        folds = object_dict(evidence.get(str(state))) or {}
        row = object_dict(folds.get("validation")) or {}
        count, wins = row.get("owners"), row.get("wins")
        if (
            type(count) is not int
            or type(wins) is not int
            or count <= 0
            or not 0 <= wins <= count
        ):
            continue
        rows.append((label, row))
    return rows


def variant_state_labels(guide: PurchaseGuide) -> str:
    return (
        ", ".join(label for label, _ in _variant_state_rows(guide)) or "State unknown"
    )


def variant_statistics(guide: PurchaseGuide, *, detailed: bool = False) -> list[str]:
    lines = []
    for label, row in _variant_state_rows(guide):
        count, wins = integer(row["owners"]), integer(row["wins"])
        text = f"{label}: {100 * wins / count:.1f}% | {wins}/{count} wins"
        if detailed:
            text += (
                f" | 95% interval {100 * numeric(row, 'lower_95'):.1f}%–{100 * numeric(row, 'upper_95'):.1f}%."
                f" State hero baseline: {100 * numeric(row, 'hero_win_rate'):.1f}% across {row['hero_matches']} matches."
            )
            cutoff = row.get("ownership_before_seconds")
            if type(cutoff) is int and cutoff > 0:
                text += f" All final core items owned before {cutoff} seconds; additional items allowed."
        lines.append(text)
    return lines


def render_ability_instructions(member: PurchaseGuide) -> list[str]:
    lines = []
    if member.ability_path:
        names = object_dict(member.evidence_summary.get("ability_names")) or {}
        lines.extend([
            "",
            "**Ability order:** "
            + " → ".join(
                str(names.get(str(item), item))
                for item in member.ability_path.ability_ids
            ),
            "Ability evidence: "
            + (
                member.ability_path.fallback_reason
                or (
                    "Build-conditioned observed order."
                    if member.ability_path.filter_item_ids
                    else "Hero-wide observed order."
                )
            ),
        ])
    imbues = {
        item.name: item.imbue_target_ability
        for item in (
            *member.core_purchase_items,
            *(item for items in member.tiers.values() for item in items),
        )
        if item.imbue_target_ability
    }
    lines.extend(f"- Imbue {item}: {ability}." for item, ability in imbues.items())
    return lines
