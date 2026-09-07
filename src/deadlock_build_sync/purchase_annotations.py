from __future__ import annotations

from typing import TYPE_CHECKING

from .build_evidence import reliable_purchase_window
from .value_validation import integer

if TYPE_CHECKING:
    from .ability_order import AbilityPath
    from .build_evidence import (
        ItemEvidence,
        SelectedHeroBuild,
    )

from .purchase_types import (
    _GENERIC_CONDITIONAL_PHRASES,
    CONDITIONAL_ANNOTATION_LABELS,
    MAX_ITEM_ANNOTATION_BYTES,
    GuideItem,
    PurchaseGuide,
)


def conditional_item_annotation(
    *,
    vs: str,
    why: str,
    swap: str,
    when: str,
    skip: str,
) -> str:
    """Create one complete conditional purchase card.

    Returns:
        Five short lines in the fixed player-facing order.

    Raises:
        ValueError: If any field is empty, generic, multiline, or too long.

    """
    values = (vs, why, swap, when, skip)
    cleaned = tuple(value.strip() for value in values)
    if any(not value or "\n" in value or "\r" in value for value in cleaned):
        raise ValueError("conditional annotation fields must be single-line text")
    annotation = "\n".join(
        f"{label}: {value}"
        for label, value in zip(CONDITIONAL_ANNOTATION_LABELS, cleaned, strict=True)
    )
    normalized = annotation.casefold()
    if any(phrase in normalized for phrase in _GENERIC_CONDITIONAL_PHRASES):
        raise ValueError("conditional annotation uses a generic trigger")
    if len(annotation.encode("utf-8")) > MAX_ITEM_ANNOTATION_BYTES:
        raise ValueError(
            f"item annotation exceeds {MAX_ITEM_ANNOTATION_BYTES} UTF-8 bytes"
        )
    return annotation


def guide_item_from_evidence(item: ItemEvidence) -> GuideItem:
    window = reliable_purchase_window(item)
    return GuideItem(
        item_id=item.item_id,
        name=item.item,
        tier=item.tier,
        purchase_event_observations=item.purchase_events,
        observed_outcome_rate=item.observed_outcome_rate,
        observed_outcome_lower_bound=0.0,
        relative_purchase_event_volume=item.selection_adoption,
        windows=(),
        eligible_player_matches=item.selection_eligible_player_matches,
        adopter_matches=item.selection_adopter_matches,
        purchase_adoption=item.selection_adoption,
        purchase_events=item.purchase_events,
        median_buy_time_s=item.selection_median_buy_time_s,
        median_valid_buy_net_worth=item.selection_median_valid_buy_net_worth,
        buy_net_worth_q25=window[0] if window is not None else None,
        buy_net_worth_q75=window[1] if window is not None else None,
        valid_buy_net_worth_share=item.selection_valid_buy_net_worth_share,
        imbue_target_ability_id=item.imbue_target_ability_id,
        imbue_target_ability=item.imbue_target_ability,
        imbue_target_matches=item.imbue_target_matches,
        imbue_observations=item.imbue_observations,
        imbue_target_share=item.imbue_target_share,
    )


def _guide_items_by_id(selected: SelectedHeroBuild) -> dict[int, GuideItem]:
    by_id = {
        item.item_id: guide_item_from_evidence(item)
        for items in selected.tiers.values()
        for item in items
    }
    for evidence_items in (
        selected.core,
        selected.core_purchase_path,
        selected.optional_core,
    ):
        for item in evidence_items:
            by_id.setdefault(item.item_id, guide_item_from_evidence(item))
    return by_id


def build_purchase_guide_from_evidence(
    hero: dict[str, object],
    selected: SelectedHeroBuild,
    *,
    ability_path: AbilityPath | None = None,
) -> PurchaseGuide:
    """Project validated player-match evidence into the analytic guide model.

    Returns:
        A state-aware economy-bounded default, optional swaps, and four adoption menus.

    """
    by_id = _guide_items_by_id(selected)
    tiers = {
        tier: tuple(by_id[item.item_id] for item in items)
        for tier, items in selected.tiers.items()
    }
    return PurchaseGuide(
        hero_id=integer(hero["id"]),
        hero_name=str(hero.get("name") or f"Hero {hero['id']}"),
        hero_class_name=str(hero.get("class_name") or ""),
        tiers=tiers,
        path_id=selected.path_id,
        path_label=selected.path_label,
        purchase_timing=selected.purchase_timing,
        automatic_branches=selected.automatic_branches,
        signature_item_ids=selected.signature_item_ids,
        ability_path=ability_path,
        core_items=tuple(by_id[item.item_id] for item in selected.core),
        core_purchase_items=tuple(
            by_id[item.item_id] for item in selected.core_purchase_path
        ),
        backbone_items=tuple(by_id[item.item_id] for item in selected.backbone),
        optional_core_items=tuple(
            by_id[item.item_id] for item in selected.optional_core
        ),
        core_alternatives=selected.core_alternatives,
        backbone_matches=selected.backbone_matches,
        backbone_share=selected.backbone_share,
        core_joint_matches=selected.core_joint_matches,
        core_joint_share=selected.core_joint_share,
        median_final_net_worth=selected.median_final_net_worth,
        core_target_cost=selected.core_target_cost,
        cohort=selected.cohort,
        evidence_summary=selected.evidence_summary,
    )
