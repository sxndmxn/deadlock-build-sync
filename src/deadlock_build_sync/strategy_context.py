from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

from .artifacts import FingerprintLayers
from .mechanics import build_hero_mechanics
from .power_curve import summarize_ending_duration_profile
from .purchase_guide import format_purchase_window
from .value_validation import integer, object_rows

if TYPE_CHECKING:
    from .api import HeroDurationStat, Patch
    from .mechanics import AbilityTimelineStep
    from .policy import BuildPolicy
    from .purchase_guide import GuideItem, PurchaseGuide
    from .snapshot import SnapshotManifest

from .strategy_context_validation import (
    CONTEXT_SCHEMA_VERSION,
    KIT_BASIS_SCHEMA_VERSION,
    NARRATIVE_BASIS_SCHEMA_VERSION,
    TIER_LABELS,
    StrategyContextError,
    build_item_mechanics_catalog,
    calculate_context_sha256,
    calculate_item_mechanics_sha256,
    calculate_kit_basis_sha256,
    calculate_narrative_basis_sha256,
    calculate_source_context_sha256,
    validate_strategy_context_document,
)

__all__ = [
    "CONTEXT_SCHEMA_VERSION",
    "KIT_BASIS_SCHEMA_VERSION",
    "NARRATIVE_BASIS_SCHEMA_VERSION",
    "StrategyContextError",
    "build_hero_strategy_context",
    "build_item_mechanics_catalog",
    "build_strategy_context_document",
    "calculate_context_sha256",
    "calculate_item_mechanics_sha256",
    "calculate_kit_basis_sha256",
    "calculate_narrative_basis_sha256",
    "calculate_source_context_sha256",
    "validate_strategy_context_document",
]


def _ability_policy(
    guide: PurchaseGuide,
    kit: dict[str, object],
    timeline: tuple[AbilityTimelineStep, ...],
) -> dict[str, object] | None:
    path = guide.ability_path
    if path is None or len(timeline) != len(path.ability_ids):
        return None
    abilities = object_rows(kit.get("abilities"))
    if abilities is None:
        return None
    names = {
        integer(ability["id"]): str(ability.get("name") or ability["id"])
        for ability in abilities
        if isinstance(ability.get("id"), int)
    }
    purchases: Counter[int] = Counter()
    steps = []
    for position, (ability_id, scheduled) in enumerate(
        zip(path.ability_ids, timeline, strict=True),
        start=1,
    ):
        prior = purchases[ability_id]
        steps.append({
            "position": position,
            "earliest_legal_level": scheduled.level,
            "ability_id": ability_id,
            "ability": names.get(ability_id, str(ability_id)),
            "action": "UNLOCK" if prior == 0 else f"UPGRADE_{prior}",
            "currency": scheduled.currency,
            "cost": scheduled.cost,
            "ability_points_remaining": scheduled.ap_remaining,
            "ability_unlocks_remaining": scheduled.unlocks_remaining,
            "decision_reached_support": path.decision_support[position - 1],
        })
        purchases[ability_id] += 1
    return {
        "selection": path.selection,
        "filter_item_ids": list(path.filter_item_ids),
        "quality": path.quality_assessment(),
        "language_ceiling": "descriptive default projection, not a universal path",
        "all_valid_telemetry_appearances": path.cohort_matches,
        "complete_path_appearances": path.complete_path_matches,
        "final_branch_support": path.matches,
        "observed_final_branch_outcome_rate": path.observed_final_branch_outcome_rate,
        "steps": steps,
    }


def _explainable_actions(
    policy: BuildPolicy | None,
    assets_by_id: dict[int, dict[str, object]],
) -> list[dict[str, object]]:
    if policy is None:
        return []
    claims = {claim.claim_id: claim for claim in policy.evidence}
    counter_cards = {card.evidence_ref: card for card in policy.counter_cards}
    result: list[dict[str, object]] = []
    for node in policy.nodes:
        if node.evidence_ref is None:
            continue
        claim = claims[node.evidence_ref]
        action_id = node.item_id if node.item_id is not None else node.ability_id
        asset = assets_by_id.get(action_id or -1, {})
        action: dict[str, object] = {
            "node_id": node.node_id,
            "kind": node.kind.value,
            "action_id": action_id,
            "action": str(asset.get("name") or action_id or node.node_id),
            "evidence_ref": node.evidence_ref,
            "claim_class": claim.claim_class.value,
            "language_ceiling": sorted(claim.language_ceiling),
            "mechanics_refs": list(claim.mechanics_refs),
            "annotation": node.annotation,
        }
        card = counter_cards.get(node.evidence_ref)
        if card is not None:
            contract = card.as_dict()
            comparator = assets_by_id.get(card.comparator_item_id, {})
            contract["item"] = str(asset.get("name") or f"Item {card.item_id}")
            contract["comparator_item"] = str(
                comparator.get("name") or f"Item {card.comparator_item_id}"
            )
            action["conditional_contract"] = contract
        result.append(action)
    return result


def _ending_duration_evidence(
    points: tuple[HeroDurationStat, ...],
    distribution: dict[str, dict[str, float | int]] | None,
) -> dict[str, object]:
    profile = summarize_ending_duration_profile(points, distribution)
    if profile is not None:
        return profile
    return {
        "estimand": "ending_duration_profile",
        "status": "abstained",
        "strongest_phase": "UNAVAILABLE",
        "weakest_phase": "UNAVAILABLE",
        "reason": (
            "The frozen cohort lacks complete supported duration buckets; no "
            "phase-strength claim is available."
        ),
        "buckets": [
            {
                "label": point.label,
                "min_duration_s": point.min_duration_s,
                "max_duration_s": point.max_duration_s,
                "matches": point.matches,
            }
            for point in points
        ],
    }


def _tier_item_context(
    item: GuideItem,
    rank: int,
    assets_by_id: dict[int, dict[str, object]],
) -> dict[str, object]:
    asset = assets_by_id.get(item.item_id, {})
    context: dict[str, object] = {
        "item_id": item.item_id,
        "item": item.name,
        "slot": str(asset.get("item_slot_type") or "unknown").upper(),
        "is_active_item": bool(asset.get("is_active_item")),
        "claim_class": "descriptive",
    }
    if item.eligible_player_matches:
        context.update({
            "rank_by_first_ownership_net_worth": rank,
            "purchase_adoption": item.purchase_adoption,
            "adopter_matches": item.adopter_matches,
            "eligible_player_matches": item.eligible_player_matches,
            "purchase_events": item.purchase_events,
            "observed_outcome_rate_among_adopters": item.observed_outcome_rate,
            "median_first_ownership_time_s": item.median_buy_time_s,
            "median_valid_first_ownership_net_worth": item.median_valid_buy_net_worth,
            "first_ownership_net_worth_q25": item.buy_net_worth_q25,
            "first_ownership_net_worth_q75": item.buy_net_worth_q75,
            "valid_first_ownership_net_worth_share": item.valid_buy_net_worth_share,
            "unit": "eligible_player_appearance",
        })
    else:
        context.update({
            "rank_by_purchase_event_volume": rank,
            "observed_purchase_event_net_worth_ranges": [
                {
                    "label": format_purchase_window(window),
                    "observed_outcome_rate": window.observed_outcome_rate,
                    "purchase_event_observations": window.matches,
                }
                for window in item.windows
            ],
            "relative_purchase_event_volume": item.relative_purchase_event_volume,
            "observed_outcome_rate": item.observed_outcome_rate,
            "purchase_event_observations": item.purchase_event_observations,
            "unit": "purchase_event",
        })
    return context


def _strategy_tiers(
    guide: PurchaseGuide,
    assets_by_id: dict[int, dict[str, object]],
) -> dict[str, list[dict[str, object]]]:
    tiers: dict[str, list[dict[str, object]]] = {}
    for tier in range(1, 5):
        tiers[TIER_LABELS[tier]] = [
            _tier_item_context(item, rank, assets_by_id)
            for rank, item in enumerate(guide.tiers.get(tier, ()), start=1)
        ]
    return tiers


def build_hero_strategy_context(
    guide: PurchaseGuide,
    hero: dict[str, object],
    assets: list[dict[str, object]],
    duration_curve: tuple[HeroDurationStat, ...] = (),
    duration_distribution: dict[str, dict[str, float | int]] | None = None,
    *,
    kit: dict[str, object] | None = None,
    ability_timeline: tuple[AbilityTimelineStep, ...] = (),
    policy: BuildPolicy | None = None,
    projection: PurchaseGuide | None = None,
    matchups: dict[str, list[dict[str, object]]] | None = None,
) -> dict[str, object]:
    """Build one closed evidence packet for explanation and review.

    Returns:
        Fingerprinted mechanics, estimands, policy, and interpretation limits.

    """
    kit = kit or build_hero_mechanics(hero, assets)
    assets_by_id = {
        integer(asset["id"]): asset
        for asset in assets
        if isinstance(asset.get("id"), int)
    }
    tiers = _strategy_tiers(guide, assets_by_id)

    ending_profile = _ending_duration_evidence(duration_curve, duration_distribution)
    explainable_actions = _explainable_actions(policy, assets_by_id)
    item_mechanics_ids = sorted(
        {item.item_id for tier_items in guide.tiers.values() for item in tier_items}
        | {item.item_id for item in guide.core_items}
        | {item.item_id for item in guide.optional_core_items}
    )
    item_mechanics = build_item_mechanics_catalog(assets, set(item_mechanics_ids))
    item_mechanics_sha256 = calculate_item_mechanics_sha256(
        item_mechanics_ids,
        item_mechanics,
    )
    projected = projection or guide
    projection_context = {
        "build": {
            "path_id": projected.path_id,
            "path_label": projected.path_label,
            "archetype": projected.build_archetype,
            "tag_ids": list(projected.build_tag_ids),
            "tag_classes": list(projected.build_tag_classes),
            "tag_labels": list(projected.build_tag_labels),
            "tag_catalog_sha256": projected.build_tag_catalog_sha256,
        },
        "categories": [
            {
                "name": category.name,
                "optional": category.optional,
                "width": category.width,
                "height": category.height,
                "items": [
                    {
                        "item_id": item.item_id,
                        "item": item.name,
                        "annotation": item.annotation,
                        "required_flex_slots": item.required_flex_slots,
                        "sell_priority": item.sell_priority,
                        "imbue_target_ability_id": item.imbue_target_ability_id,
                    }
                    for item in category.items
                ],
            }
            for category in projected.rendered_categories
        ],
        "semantics": (
            "CORE ITEMS is the component-expanded non-optional Queue path. "
            "OPTIONAL CORE contains only admitted like-state non-backbone CORE "
            "substitutions. "
            "OPTIONAL CORE and TIER 1–4 never enter the automatic Queue."
        ),
    }
    context: dict[str, object] = {
        "hero_id": guide.hero_id,
        "hero": guide.hero_name,
        "path_id": guide.path_id,
        "path_label": guide.path_label,
        "snapshot_id": guide.snapshot_id,
        "policy_id": guide.policy_id,
        "hero_mechanics": kit,
        "item_mechanics_ids": item_mechanics_ids,
        "item_mechanics_sha256": item_mechanics_sha256,
        "ability_policy": _ability_policy(guide, kit, ability_timeline),
        "ending_duration_profile": ending_profile,
        "core": {
            "selection": "temporally stable supported backbone with a mechanically legal conditional-support completion",
            "backbone_item_ids": [item.item_id for item in guide.backbone_items],
            "backbone_player_matches": guide.backbone_matches,
            "backbone_share": guide.backbone_share,
            "item_ids_in_observed_acquisition_order": [
                item.item_id for item in guide.core_items
            ],
            "component_expanded_purchase_path": [
                item.item_id for item in (guide.core_purchase_items or guide.core_items)
            ],
            "joint_player_matches": guide.core_joint_matches,
            "joint_share": guide.core_joint_share,
            "eligible_player_matches": (
                guide.core_items[0].eligible_player_matches if guide.core_items else 0
            ),
            "median_final_net_worth": guide.median_final_net_worth,
            "core_target_cost": guide.core_target_cost,
            "items": [
                {
                    "item_id": item.item_id,
                    "item": item.name,
                    "purchase_adoption": item.purchase_adoption,
                    "adopter_matches": item.adopter_matches,
                    "eligible_player_matches": item.eligible_player_matches,
                    "observed_outcome_rate_among_adopters": item.observed_outcome_rate,
                    "median_first_ownership_time_s": item.median_buy_time_s,
                    "median_valid_first_ownership_net_worth": item.median_valid_buy_net_worth,
                }
                for item in guide.core_items
            ],
            "optional_core_substitution_cards": [
                card.__dict__ for card in guide.core_alternatives
            ],
        },
        "tiers": tiers,
        "matchups": matchups or {"same_lane": [], "whole_enemy_team": []},
        "policy": policy.as_dict() if policy is not None else None,
        "explainable_actions": explainable_actions,
        "projection": projection_context,
        "interpretation_constraints": [
            "Tier membership is player-match first-ownership adoption; left-to-right display order is observed net-worth timing, not outcome rate.",
            "Observed adopter outcomes and ending-duration profiles are descriptive associations, not item effects or live power curves.",
            "Ability actions use reached-state support and exact legal levels; price tiers are not ability quarters.",
            "Only mechanics-backed, state-observable policy branches may be explained.",
            "CORE ITEMS is the component-expanded automatic Queue path; OPTIONAL CORE contains gated non-backbone CORE substitutions, and all optional rows remain outside Queue.",
            "Cross-fitted doubly robust contrasts are assumption-dependent like-state estimates, not proof that an item causes wins.",
            "Conditional item cards must use VS, WHY, SWAP, WHEN, and SKIP lines grounded in both item mechanics; they must not state an outcome effect.",
            "Do not invent mechanics, numeric effects, threats, combos, or matchups absent from this packet.",
        ],
    }
    context["fingerprints"] = FingerprintLayers.calculate(
        mechanics={
            "hero": kit,
            "items_sha256": item_mechanics_sha256,
        },
        analytics={
            "ability_policy": context["ability_policy"],
            "ending_duration_profile": context["ending_duration_profile"],
            "core": context["core"],
            "tiers": tiers,
            "matchups": context["matchups"],
        },
        policy_basis=context["policy"],
        narrative={
            "interpretation_constraints": context["interpretation_constraints"],
        },
        projection=projection_context,
    ).as_dict()
    context["kit_basis_sha256"] = calculate_kit_basis_sha256(context)
    context["narrative_basis_sha256"] = calculate_narrative_basis_sha256(context)
    context["context_sha256"] = calculate_context_sha256(context)
    return context


def build_strategy_context_document(
    patch: Patch,
    contexts: list[dict[str, object]],
    *,
    manifest: SnapshotManifest,
    item_mechanics: dict[str, dict[str, object]],
    requested_hero_ids: set[int],
    exclusions: tuple[tuple[int, str], ...] = (),
) -> dict[str, object]:
    """Build a complete, snapshot-bound multi-hero context artifact.

    Returns:
        A document with exact roster coverage and a full source manifest.

    """
    document = {
        "schema_version": CONTEXT_SCHEMA_VERSION,
        "snapshot_manifest": manifest.as_dict(),
        "patch": patch.as_dict(),
        "filters": {
            "game_mode": manifest.game_mode,
            "match_mode": manifest.match_mode.value,
            "rank_range": manifest.rank_range,
            "as_of_timestamp": manifest.as_of_timestamp,
            "client_version": manifest.client_version,
            "epochs": manifest.epochs.as_dict(),
            "outcome_policy": manifest.outcome_policy.as_dict(
                enforced=manifest.outcome_policy_enforced
            ),
            "minimum_decision_support": 1,
            "low_decision_support_warning_threshold": 20,
        },
        "requested_hero_ids": sorted(requested_hero_ids),
        "exclusions": [
            {"hero_id": hero_id, "reason": reason}
            for hero_id, reason in sorted(exclusions)
        ],
        "item_mechanics": {
            key: item_mechanics[key] for key in sorted(item_mechanics, key=int)
        },
        "heroes": contexts,
    }
    document["source_context_sha256"] = calculate_source_context_sha256(document)
    validate_strategy_context_document(document)
    return document
