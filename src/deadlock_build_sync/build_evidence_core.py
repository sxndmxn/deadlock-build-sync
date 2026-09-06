from __future__ import annotations

from typing import TYPE_CHECKING, cast

from .artifacts import ArtifactError
from .build_evidence_core_alternative import parse_core_alternative
from .build_evidence_item import _item
from .build_evidence_types import (
    CORE_POLICY_VERSION,
    MAXIMUM_BACKBONE_ITEM_COUNT,
    MAXIMUM_CORE_ALTERNATIVES,
    MAXIMUM_CORE_ITEM_COUNT,
    MAXIMUM_TIER_ADOPTION_DRIFT,
    MINIMUM_BACKBONE_ITEM_COUNT,
    MINIMUM_CORE_SUPPORT,
    MINIMUM_TIER_ADOPTION,
    MINIMUM_TIER_SUPPORT,
    TIER_ITEM_COUNT,
    TIER_POLICY_VERSION,
    CoreAlternativeEvidence,
    CorePolicyEvidence,
    ItemEvidence,
    TierPolicyEvidence,
)
from .build_evidence_values import (
    _document,
    _required_int,
)
from .value_validation import object_dict, object_list

if TYPE_CHECKING:
    from collections.abc import Sequence


def _hero_items(
    raw_items: Sequence[object],
    hero_id: int,
    eligible: int,
) -> tuple[tuple[ItemEvidence, ...], list[int]]:
    items = tuple(_item(row, hero_id) for row in raw_items)
    item_ids = [item.item_id for item in items]
    if len(item_ids) != len(set(item_ids)):
        raise ArtifactError(f"hero {hero_id} has duplicate item evidence")
    if any(item.eligible_player_matches != eligible for item in items):
        raise ArtifactError(f"hero {hero_id} item denominators disagree")
    return items, item_ids


def _core_alternative(
    value: object,
    hero_id: int,
    item_ids: set[int],
    default_item_ids: set[int],
) -> CoreAlternativeEvidence:
    return parse_core_alternative(value, hero_id, item_ids, default_item_ids)


def _core_policy_document(value: object, hero_id: int) -> dict[str, object]:
    document = object_dict(value)
    if document is None or document.get("version") != CORE_POLICY_VERSION:
        raise ArtifactError(f"hero {hero_id} has no supported core policy")
    return document


def _policy_list(document: dict[str, object], field: str, hero_id: int) -> list[object]:
    value = object_list(document.get(field))
    if value is None:
        raise ArtifactError(f"hero {hero_id} has an incomplete core policy")
    return value


def _policy_mapping(
    document: dict[str, object], field: str, hero_id: int
) -> dict[str, object]:
    value = object_dict(document.get(field))
    if value is None:
        raise ArtifactError(f"hero {hero_id} has an incomplete core policy")
    return value


def _core_membership(
    raw_backbone: list[object],
    raw_default: list[object],
    hero_id: int,
    item_ids: set[int],
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    backbone = tuple(
        _required_int(item_id, "backbone item id", minimum=1)
        for item_id in raw_backbone
    )
    default = tuple(
        _required_int(item_id, "default core item id", minimum=1)
        for item_id in raw_default
    )
    valid = (
        MINIMUM_BACKBONE_ITEM_COUNT <= len(backbone) <= MAXIMUM_BACKBONE_ITEM_COUNT
        and len(backbone) == len(set(backbone))
        and len(backbone) <= len(default) <= MAXIMUM_CORE_ITEM_COUNT
        and len(default) == len(set(default))
        and set(backbone) <= set(default) <= item_ids
    )
    if not valid:
        raise ArtifactError(f"hero {hero_id} has invalid core policy membership")
    return backbone, default


def _policy_support(
    document: dict[str, object],
    raw_folds: dict[str, object],
    hero_id: int,
    eligible: int,
    label: str,
) -> tuple[int, dict[str, int]]:
    folds = {
        fold: _required_int(
            raw_folds.get(fold),
            f"{fold} {label} support",
            minimum=0 if fold == "test" else MINIMUM_CORE_SUPPORT,
        )
        for fold in ("train", "validation", "test")
    }
    matches = _required_int(
        document.get(f"{label}_matches"),
        f"{label} support",
        minimum=folds["train"] + folds["validation"] if label == "backbone" else 0,
    )
    selection_matches = folds["train"] + folds["validation"]
    if matches != selection_matches or matches > eligible:
        raise ArtifactError(f"hero {hero_id} {label} support exceeds its cohort")
    return matches, folds


def _core_alternatives(
    rows: list[object],
    hero_id: int,
    item_ids: set[int],
    default: tuple[int, ...],
) -> tuple[CoreAlternativeEvidence, ...]:
    alternatives = tuple(
        _core_alternative(row, hero_id, item_ids, set(default)) for row in rows
    )
    valid = (
        len(alternatives) <= MAXIMUM_CORE_ALTERNATIVES
        and len({alternative.item_id for alternative in alternatives})
        == len(alternatives)
        and all(alternative.stage <= len(default) for alternative in alternatives)
    )
    if not valid:
        raise ArtifactError(f"hero {hero_id} has invalid core alternatives")
    return alternatives


def _candidate_audit(rows: list[object], hero_id: int) -> tuple[dict[str, object], ...]:
    if any(not isinstance(row, dict) for row in rows):
        raise ArtifactError(f"hero {hero_id} has a malformed core candidate audit")
    return tuple(
        _document(row, f"hero {hero_id} has a malformed core candidate audit")
        for row in rows
    )


def _core_policy(
    value: object,
    hero_id: int,
    item_ids: set[int],
    eligible: int,
) -> CorePolicyEvidence:
    document = _core_policy_document(value, hero_id)
    raw_backbone = _policy_list(document, "backbone_item_ids", hero_id)
    raw_default = _policy_list(document, "default_item_ids", hero_id)
    raw_alternatives = _policy_list(document, "alternatives", hero_id)
    raw_audit = _policy_list(document, "candidate_audit", hero_id)
    raw_fold_matches = _policy_mapping(document, "backbone_fold_matches", hero_id)
    raw_default_folds = _policy_mapping(document, "default_fold_matches", hero_id)
    evaluation = _policy_mapping(document, "evaluation", hero_id)
    backbone, default = _core_membership(raw_backbone, raw_default, hero_id, item_ids)
    backbone_matches, fold_matches = _policy_support(
        document, raw_fold_matches, hero_id, eligible, "backbone"
    )
    alternatives = _core_alternatives(raw_alternatives, hero_id, item_ids, default)
    default_matches, default_fold_matches = _policy_support(
        document, raw_default_folds, hero_id, eligible, "default"
    )
    return CorePolicyEvidence(
        backbone_item_ids=backbone,
        default_item_ids=default,
        backbone_matches=backbone_matches,
        backbone_fold_matches=fold_matches,
        default_matches=default_matches,
        default_fold_matches=default_fold_matches,
        alternatives=alternatives,
        candidate_audit=_candidate_audit(raw_audit, hero_id),
        evaluation=evaluation,
    )


def _tier_policy(
    value: object,
    hero_id: int,
    items: tuple[ItemEvidence, ...],
) -> TierPolicyEvidence:
    if not isinstance(value, dict) or value.get("version") != TIER_POLICY_VERSION:
        raise ArtifactError(f"hero {hero_id} has no supported tier policy")
    raw_membership_value = value.get("item_ids_by_tier")
    if not isinstance(raw_membership_value, dict) or set(raw_membership_value) != {
        "1",
        "2",
        "3",
        "4",
    }:
        raise ArtifactError(f"hero {hero_id} has an incomplete tier policy")
    raw_membership = cast("dict[str, object]", raw_membership_value)
    discovery_pool = value.get("source_fold") == "discovery"
    by_id = {item.item_id: item for item in items}
    item_ids_by_tier: dict[int, tuple[int, ...]] = {}
    for tier in range(1, 5):
        raw_item_ids = raw_membership[str(tier)]
        if not isinstance(raw_item_ids, list):
            raise ArtifactError(f"hero {hero_id} has a malformed Tier {tier} policy")
        item_ids = tuple(
            _required_int(item_id, "tier policy item id", minimum=1)
            for item_id in raw_item_ids
        )
        if not 1 <= len(item_ids) <= TIER_ITEM_COUNT or len(item_ids) != len(
            set(item_ids)
        ):
            raise ArtifactError(f"hero {hero_id} has invalid Tier {tier} membership")
        for item_id in item_ids:
            item = by_id.get(item_id)
            if not _supported_pool_item(item, tier, discovery=discovery_pool):
                raise ArtifactError(
                    f"hero {hero_id} has an unsupported Tier {tier} item"
                )
        item_ids_by_tier[tier] = item_ids
    return TierPolicyEvidence(item_ids_by_tier, discovery_pool)


def _supported_pool_item(
    item: ItemEvidence | None, tier: int, *, discovery: bool
) -> bool:
    if (
        item is None
        or item.tier != tier
        or item.training_adopter_matches < MINIMUM_TIER_SUPPORT
    ):
        return False
    return discovery or (
        item.validation_adopter_matches >= MINIMUM_TIER_SUPPORT
        and min(item.training_adoption, item.validation_adoption)
        >= MINIMUM_TIER_ADOPTION
        and abs(item.training_adoption - item.validation_adoption)
        <= MAXIMUM_TIER_ADOPTION_DRIFT
    )
