from __future__ import annotations

import hashlib
import json
from collections import Counter
from typing import TYPE_CHECKING, Any

from .artifacts import FingerprintLayers
from .build_tags import AXIS_CLASSES, COMPLEXITY_CLASS, FUNCTION_CLASSES
from .mechanics import build_hero_mechanics, extract_asset_mechanics
from .power_curve import summarize_ending_duration_profile
from .purchase_guide import format_purchase_window

if TYPE_CHECKING:
    from .api import HeroDurationStat, Patch
    from .mechanics import AbilityTimelineStep
    from .policy import BuildPolicy
    from .purchase_guide import PurchaseGuide
    from .snapshot import SnapshotManifest

CONTEXT_SCHEMA_VERSION = 8
KIT_BASIS_SCHEMA_VERSION = 2
NARRATIVE_BASIS_SCHEMA_VERSION = 6
TIER_LABELS = {1: "I", 2: "II", 3: "III", 4: "IV"}


class StrategyContextError(ValueError):
    """Raised when an exported strategy context is malformed or was edited."""


def _validate_build_identity(entry: dict[str, Any], manifest: dict[str, Any]) -> None:
    projection = entry.get("projection")
    build = projection.get("build") if isinstance(projection, dict) else None
    if not isinstance(build, dict):
        raise StrategyContextError("strategy context has no build identity")
    ids = build.get("tag_ids")
    classes = build.get("tag_classes")
    labels = build.get("tag_labels")
    valid = (
        isinstance(ids, list)
        and len(ids) == 3
        and all(isinstance(value, int) and value > 0 for value in ids)
        and len(set(ids)) == 3
        and isinstance(classes, list)
        and len(classes) == 3
        and isinstance(labels, list)
        and len(labels) == 3
    )
    if not valid:
        raise StrategyContextError("strategy context has invalid build tags")
    if (
        classes[0] not in AXIS_CLASSES
        or classes[1] not in FUNCTION_CLASSES
        or classes[2] != COMPLEXITY_CLASS
        or build.get("tag_catalog_sha256") != manifest.get("build_tags_sha256")
        or not isinstance(build.get("archetype"), str)
        or not build["archetype"].strip()
    ):
        raise StrategyContextError("strategy context has invalid build tags")


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _narrative_basis(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": NARRATIVE_BASIS_SCHEMA_VERSION,
        "hero_id": context.get("hero_id"),
        "hero": context.get("hero"),
        "hero_description": context.get("hero_description"),
        "hero_mechanics": context.get("hero_mechanics"),
        "ability_policy": context.get("ability_policy"),
        "ending_duration_profile": context.get("ending_duration_profile"),
        "core": context.get("core"),
        "tiers": context.get("tiers"),
        "policy": context.get("policy"),
        "explainable_actions": context.get("explainable_actions"),
        "projection": context.get("projection"),
        "fingerprints": context.get("fingerprints"),
        "matchups": context.get("matchups"),
        "interpretation_constraints": context.get("interpretation_constraints"),
    }


def _kit_basis(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": KIT_BASIS_SCHEMA_VERSION,
        "hero_id": context.get("hero_id"),
        "hero": context.get("hero"),
        "hero_description": context.get("hero_description"),
        "hero_mechanics": context.get("hero_mechanics"),
        "ability_policy": context.get("ability_policy"),
    }


def calculate_kit_basis_sha256(context: dict[str, Any]) -> str:
    """Return the ability-only tactical fingerprint for one hero context.

    Returns:
        A lowercase hexadecimal SHA-256 digest.

    """
    return _canonical_hash(_kit_basis(context))


def calculate_narrative_basis_sha256(context: dict[str, Any]) -> str:
    """Return the tactical-basis fingerprint for one hero context.

    Returns:
        A lowercase hexadecimal SHA-256 digest.

    """
    return _canonical_hash(_narrative_basis(context))


def calculate_context_sha256(context: dict[str, Any]) -> str:
    """Return the full fingerprint for one hero context.

    Returns:
        A lowercase hexadecimal SHA-256 digest.

    """
    payload = dict(context)
    payload.pop("context_sha256", None)
    return _canonical_hash(payload)


def calculate_source_context_sha256(document: dict[str, Any]) -> str:
    """Return the fingerprint for a complete exported context document.

    Returns:
        A lowercase hexadecimal SHA-256 digest.

    """
    payload = dict(document)
    payload.pop("source_context_sha256", None)
    return _canonical_hash(payload)


def validate_strategy_context_document(document: dict[str, Any]) -> None:
    """Verify schema, coverage, snapshot, hero, and full export fingerprints.

    Raises:
        StrategyContextError: If the document is malformed, stale, or edited.

    """
    if document.get("schema_version") != CONTEXT_SCHEMA_VERSION:
        raise StrategyContextError("unsupported strategy-context schema")
    manifest = document.get("snapshot_manifest")
    if not isinstance(manifest, dict) or not isinstance(
        manifest.get("snapshot_id"), str
    ):
        raise StrategyContextError("strategy context is missing its snapshot manifest")
    heroes = document.get("heroes")
    if not isinstance(heroes, list):
        raise StrategyContextError("strategy context is missing its heroes array")
    requested = document.get("requested_hero_ids")
    exclusions = document.get("exclusions")
    if not isinstance(requested, list) or not all(
        isinstance(hero_id, int) for hero_id in requested
    ):
        raise StrategyContextError("strategy context has invalid requested heroes")
    if not isinstance(exclusions, list) or not all(
        isinstance(exclusion, dict)
        and isinstance(exclusion.get("hero_id"), int)
        and isinstance(exclusion.get("reason"), str)
        and bool(exclusion["reason"].strip())
        for exclusion in exclusions
    ):
        raise StrategyContextError("strategy context has invalid exclusions")

    seen_hero_ids: set[int] = set()
    for entry in heroes:
        if not isinstance(entry, dict) or not isinstance(entry.get("hero_id"), int):
            raise StrategyContextError("strategy context contains an invalid hero")
        hero_id = int(entry["hero_id"])
        if hero_id in seen_hero_ids:
            raise StrategyContextError(
                f"strategy context contains duplicate hero {hero_id}"
            )
        seen_hero_ids.add(hero_id)
        hero_name = str(entry.get("hero") or hero_id)
        if entry.get("snapshot_id") != manifest["snapshot_id"]:
            raise StrategyContextError(
                f"strategy context snapshot differs for {hero_name}"
            )
        _validate_build_identity(entry, manifest)
        if entry.get("kit_basis_sha256") != calculate_kit_basis_sha256(entry):
            raise StrategyContextError(
                f"strategy context kit basis was edited for {hero_name}; "
                "run export-context again"
            )
        if entry.get("narrative_basis_sha256") != calculate_narrative_basis_sha256(
            entry
        ):
            raise StrategyContextError(
                f"strategy context tactical basis was edited for {hero_name}; "
                "run export-context again"
            )
        if entry.get("context_sha256") != calculate_context_sha256(entry):
            raise StrategyContextError(
                f"strategy context was edited for {hero_name}; run export-context again"
            )
    excluded_ids = {int(exclusion["hero_id"]) for exclusion in exclusions}
    if seen_hero_ids | excluded_ids != set(requested):
        raise StrategyContextError("strategy context does not cover requested heroes")
    if seen_hero_ids & excluded_ids:
        raise StrategyContextError("strategy context both includes and excludes a hero")
    if document.get("source_context_sha256") != calculate_source_context_sha256(
        document
    ):
        raise StrategyContextError(
            "strategy context document was edited; run export-context again"
        )


def _ability_policy(
    guide: PurchaseGuide,
    kit: dict[str, Any],
    timeline: tuple[AbilityTimelineStep, ...],
) -> dict[str, Any] | None:
    path = guide.ability_path
    if path is None or len(timeline) != len(path.ability_ids):
        return None
    abilities = kit.get("abilities")
    if not isinstance(abilities, list):
        return None
    names = {
        int(ability["id"]): str(ability.get("name") or ability["id"])
        for ability in abilities
        if isinstance(ability, dict) and isinstance(ability.get("id"), int)
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
        "language_ceiling": "descriptive default projection, not a universal path",
        "all_valid_telemetry_appearances": path.cohort_matches,
        "complete_path_appearances": path.complete_path_matches,
        "final_branch_support": path.matches,
        "observed_final_branch_outcome_rate": path.observed_final_branch_outcome_rate,
        "steps": steps,
    }


def _explainable_actions(
    policy: BuildPolicy | None,
    assets_by_id: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    if policy is None:
        return []
    claims = {claim.claim_id: claim for claim in policy.evidence}
    counter_cards = {card.evidence_ref: card for card in policy.counter_cards}
    result: list[dict[str, Any]] = []
    for node in policy.nodes:
        if node.evidence_ref is None:
            continue
        claim = claims[node.evidence_ref]
        action_id = node.item_id if node.item_id is not None else node.ability_id
        asset = assets_by_id.get(action_id or -1, {})
        action: dict[str, Any] = {
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
) -> dict[str, Any]:
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


def build_hero_strategy_context(
    guide: PurchaseGuide,
    hero: dict[str, Any],
    assets: list[dict[str, Any]],
    duration_curve: tuple[HeroDurationStat, ...] = (),
    duration_distribution: dict[str, dict[str, float | int]] | None = None,
    *,
    kit: dict[str, Any] | None = None,
    ability_timeline: tuple[AbilityTimelineStep, ...] = (),
    policy: BuildPolicy | None = None,
    projection: PurchaseGuide | None = None,
    matchups: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Build one closed evidence packet for explanation and review.

    Returns:
        Fingerprinted mechanics, estimands, policy, and interpretation limits.

    """
    kit = kit or build_hero_mechanics(hero, assets)
    assets_by_id = {
        int(asset["id"]): asset for asset in assets if isinstance(asset.get("id"), int)
    }
    tiers: dict[str, list[dict[str, Any]]] = {}
    for tier in range(1, 5):
        tier_items = []
        for rank, item in enumerate(guide.tiers.get(tier, ()), start=1):
            asset = assets_by_id.get(item.item_id, {})
            item_context = {
                "item_id": item.item_id,
                "item": item.name,
                "slot": str(asset.get("item_slot_type") or "unknown").upper(),
                "is_active_item": bool(asset.get("is_active_item")),
                "mechanics": extract_asset_mechanics(asset) if asset else {},
                "claim_class": "descriptive",
            }
            if item.eligible_player_matches:
                item_context.update({
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
                item_context.update({
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
            tier_items.append(item_context)
        tiers[TIER_LABELS[tier]] = tier_items

    ending_profile = _ending_duration_evidence(duration_curve, duration_distribution)
    explainable_actions = _explainable_actions(policy, assets_by_id)
    projected = projection or guide
    projection_context = {
        "build": {
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
            "CORE ITEMS is the only non-optional Queue row. TIER 1–4 are optional "
            "adoption reference menus and never automatic purchases."
        ),
    }
    context: dict[str, Any] = {
        "hero_id": guide.hero_id,
        "hero": guide.hero_name,
        "snapshot_id": guide.snapshot_id,
        "policy_id": guide.policy_id,
        "hero_description": kit.get("description"),
        "hero_mechanics": kit,
        "abilities": kit.get("abilities"),
        "ability_policy": _ability_policy(guide, kit, ability_timeline),
        "ending_duration_profile": ending_profile,
        "core": {
            "selection": "highest joint-support legal eight-item final inventory within median final net worth",
            "item_ids_in_observed_acquisition_order": [
                item.item_id for item in guide.core_items
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
                    "mechanics": (
                        extract_asset_mechanics(assets_by_id[item.item_id])
                        if item.item_id in assets_by_id
                        else {}
                    ),
                    "purchase_adoption": item.purchase_adoption,
                    "adopter_matches": item.adopter_matches,
                    "eligible_player_matches": item.eligible_player_matches,
                    "observed_outcome_rate_among_adopters": item.observed_outcome_rate,
                    "median_first_ownership_time_s": item.median_buy_time_s,
                    "median_valid_first_ownership_net_worth": item.median_valid_buy_net_worth,
                }
                for item in guide.core_items
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
            "CORE ITEMS is the only automatic Queue; TIER 1–4 are optional reference menus and do not prove a situational trigger.",
            "Do not invent mechanics, numeric effects, threats, combos, or matchups absent from this packet.",
        ],
    }
    context["fingerprints"] = FingerprintLayers.calculate(
        mechanics=kit,
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
    contexts: list[dict[str, Any]],
    *,
    manifest: SnapshotManifest,
    requested_hero_ids: set[int],
    exclusions: tuple[tuple[int, str], ...] = (),
) -> dict[str, Any]:
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
        "heroes": contexts,
    }
    document["source_context_sha256"] = calculate_source_context_sha256(document)
    validate_strategy_context_document(document)
    return document
