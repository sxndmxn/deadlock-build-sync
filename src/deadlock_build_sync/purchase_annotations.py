from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from .build_evidence import reliable_purchase_window
from .mechanics import optional_item_decision, power_spike_text
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
    MAX_ITEM_ANNOTATION_CHARS,
    MAX_TACTICAL_INSTRUCTION_BYTES,
    POWER_SPIKE_LABEL,
    TIER_ANNOTATION_LABELS,
    GuideItem,
    PurchaseGuide,
    _format_observed_purchase_window,
    item_stat_context,
)


def tactical_item_annotation(instruction: str, item: GuideItem) -> str:
    """Compose an action-first annotation within Steam's UTF-8 byte ceiling.

    Returns:
        The bounded tactical and observational annotation.

    Raises:
        ValueError: If the tactical instruction exceeds its UTF-8 contract.

    """
    action = instruction.strip()
    if not action or len(action.encode("utf-8")) > MAX_TACTICAL_INSTRUCTION_BYTES:
        raise ValueError(
            "tactical instruction must be 1–"
            f"{MAX_TACTICAL_INSTRUCTION_BYTES} UTF-8 bytes"
        )
    context = item_stat_context(item)
    combined = f"{action}\n{context}"
    annotation = (
        combined
        if len(combined.encode("utf-8")) <= MAX_ITEM_ANNOTATION_BYTES
        else context
    )
    if len(annotation.encode("utf-8")) > MAX_ITEM_ANNOTATION_BYTES:
        raise ValueError(
            f"item annotation exceeds {MAX_ITEM_ANNOTATION_BYTES} UTF-8 bytes"
        )
    return annotation


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


def tier_item_annotation(
    *,
    use: str,
    why: str,
    skip: str,
    item: GuideItem,
) -> str:
    """Create one deterministic tactical card for a normal tier item.

    Returns:
        Four bounded lines without raw win-rate data.

    Raises:
        ValueError: If the copy is incomplete or exceeds the Steam byte limit.

    """
    window = _format_observed_purchase_window(
        item.buy_net_worth_q25,
        item.buy_net_worth_q75,
    )
    data = (
        f"{window} • PICK {item.purchase_adoption * 100:.1f}% "
        f"• BUYERS {item.adopter_matches:,}"
    )
    cleaned = tuple(value.strip() for value in (use, why, skip, data))
    if any(not value or "\n" in value or "\r" in value for value in cleaned):
        raise ValueError("tier annotation fields must be single-line text")
    annotation = "\n".join(
        f"{label}: {value}"
        for label, value in zip(TIER_ANNOTATION_LABELS, cleaned, strict=True)
    )
    validate_tier_annotation(annotation)
    return annotation


def validate_tier_annotation(annotation: str) -> None:
    """Validate the fixed normal-tier annotation contract.

    Raises:
        ValueError: If the annotation does not match the bounded four-line format.

    """
    lines = annotation.splitlines()
    if len(lines) != len(TIER_ANNOTATION_LABELS) or any(
        not line.startswith(f"{label}: ") or not line.removeprefix(f"{label}: ").strip()
        for label, line in zip(TIER_ANNOTATION_LABELS, lines, strict=True)
    ):
        raise ValueError("tier annotation must contain USE, WHY, SKIP, and DATA")
    if len(annotation.encode("utf-8")) > MAX_ITEM_ANNOTATION_BYTES:
        raise ValueError(
            f"item annotation exceeds {MAX_ITEM_ANNOTATION_BYTES} UTF-8 bytes"
        )


def split_power_spike(annotation: str) -> tuple[str, str]:
    """Separate a leading power spike line from the rest of an annotation.

    Returns:
        The spike text (empty when absent) and the remaining annotation body.

    Raises:
        ValueError: If a power spike line has no text or no body after it.

    """
    prefix = f"{POWER_SPIKE_LABEL}: "
    if not annotation.startswith(prefix):
        return "", annotation
    spike, _, body = annotation.removeprefix(prefix).partition("\n")
    if not spike.strip() or not body.strip():
        raise ValueError("power spike line needs text and a following annotation")
    return spike, body


def _with_power_spike(
    item: GuideItem,
    asset: dict[str, object] | None,
    hero_mechanics: dict[str, object] | None,
) -> GuideItem:
    if asset is None:
        return item
    budget = (
        MAX_ITEM_ANNOTATION_CHARS - len(item.annotation) - len(POWER_SPIKE_LABEL) - 3
    )
    spike = power_spike_text(asset, hero_mechanics, max_chars=budget)
    return replace(item, power_spike=spike)


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


def _annotated_tier_item(
    item: GuideItem,
    asset: dict[str, object] | None,
    hero_mechanics: dict[str, object] | None,
) -> GuideItem | None:
    if asset is None:
        return None
    decision = optional_item_decision(asset, hero_mechanics=hero_mechanics)
    if decision is None:
        return None
    use, why, skip = decision
    try:
        annotation = tier_item_annotation(use=use, why=why, skip=skip, item=item)
    except ValueError:
        return None
    annotated = replace(item, verified_tier_annotation=annotation)
    return _with_power_spike(annotated, asset, hero_mechanics)


def _assets_by_id(
    assets: list[dict[str, object]] | None,
) -> dict[int, dict[str, object]] | None:
    if assets is None:
        return None
    return {
        integer(asset["id"]): asset
        for asset in assets
        if isinstance(asset.get("id"), int)
    }


def _spike_core_items(
    by_id: dict[int, GuideItem],
    selected: SelectedHeroBuild,
    assets_by_id: dict[int, dict[str, object]] | None,
    hero_mechanics: dict[str, object] | None,
) -> None:
    if assets_by_id is None:
        return
    core_ids = {item.item_id for item in (*selected.core, *selected.core_purchase_path)}
    for item_id in core_ids:
        by_id[item_id] = _with_power_spike(
            by_id[item_id], assets_by_id.get(item_id), hero_mechanics
        )


def _project_tiers(
    selected: SelectedHeroBuild,
    by_id: dict[int, GuideItem],
    assets_by_id: dict[int, dict[str, object]] | None,
    hero_mechanics: dict[str, object] | None,
) -> dict[int, tuple[GuideItem, ...]]:
    tiers = {
        tier: tuple(by_id[item.item_id] for item in items)
        for tier, items in selected.tiers.items()
    }
    if assets_by_id is None:
        return tiers
    annotated_tiers: dict[int, tuple[GuideItem, ...]] = {}
    for tier, items in tiers.items():
        annotated = (
            projected
            for item in items
            if (
                projected := _annotated_tier_item(
                    item, assets_by_id.get(item.item_id), hero_mechanics
                )
            )
            is not None
        )
        annotated_tiers[tier] = tuple(annotated)
    return annotated_tiers


def build_purchase_guide_from_evidence(
    hero: dict[str, object],
    selected: SelectedHeroBuild,
    *,
    ability_path: AbilityPath | None = None,
    assets: list[dict[str, object]] | None = None,
    hero_mechanics: dict[str, object] | None = None,
) -> PurchaseGuide:
    """Project validated player-match evidence into the analytic guide model.

    Returns:
        A state-aware economy-bounded default, optional swaps, and four adoption menus.

    """
    by_id = _guide_items_by_id(selected)
    assets_by_id = _assets_by_id(assets)
    tiers = _project_tiers(selected, by_id, assets_by_id, hero_mechanics)
    _spike_core_items(by_id, selected, assets_by_id, hero_mechanics)
    return PurchaseGuide(
        hero_id=integer(hero["id"]),
        hero_name=str(hero.get("name") or f"Hero {hero['id']}"),
        hero_class_name=str(hero.get("class_name") or ""),
        tiers=tiers,
        path_id=selected.path_id,
        path_label=selected.path_label,
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
    )
