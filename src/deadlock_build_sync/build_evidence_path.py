from __future__ import annotations

from .artifacts import ArtifactError
from .build_evidence_core import _core_policy, _hero_items, _tier_policy
from .build_evidence_references import validate_policy_item_references
from .build_evidence_sequence import _sequence_policy, _situational_policy
from .build_evidence_types import HeroBuildEvidence, ItemEvidence
from .build_evidence_values import _required_int
from .value_validation import object_dict, object_list


def _path_identity(
    document: dict[str, object], hero_id: int
) -> tuple[str, str, tuple[int, ...], dict[str, object]]:
    path_id = document.get("path_id")
    path_label = document.get("path_label")
    raw_signature = object_list(document.get("signature_item_ids"))
    discovery = object_dict(document.get("discovery"))
    if not isinstance(path_id, str) or not path_id.strip():
        raise ArtifactError(f"hero {hero_id} has an invalid build path identity")
    if not isinstance(path_label, str) or not path_label.strip():
        raise ArtifactError(f"hero {hero_id} has an invalid build path identity")
    if raw_signature is None or discovery is None:
        raise ArtifactError(f"hero {hero_id} has an invalid build path identity")
    if any(not isinstance(item_id, int) or item_id <= 0 for item_id in raw_signature):
        raise ArtifactError(f"hero {hero_id} has an invalid build path identity")
    signature = tuple(
        _required_int(item_id, "signature item id", minimum=1)
        for item_id in raw_signature
    )
    if len(signature) != len(set(signature)):
        raise ArtifactError(f"hero {hero_id} has an invalid build path identity")
    return path_id.strip(), path_label.strip(), signature, discovery


def _path_cohort(
    document: dict[str, object], hero_id: int
) -> tuple[int, int, dict[str, int]]:
    eligible = _required_int(
        document.get("eligible_player_matches"),
        "eligible player matches",
        minimum=1,
    )
    raw_folds = object_dict(document.get("fold_eligible_player_matches"))
    if raw_folds is None:
        raise ArtifactError(f"hero {hero_id} lacks fold cohort counts")
    folds = {
        fold: _required_int(
            raw_folds.get(fold),
            f"{fold} eligible player matches",
            minimum=0 if fold == "test" else 1,
        )
        for fold in ("train", "validation", "test")
    }
    selection = _required_int(
        document.get("selection_eligible_player_matches"),
        "selection eligible player matches",
        minimum=1,
    )
    if sum(folds.values()) != eligible:
        raise ArtifactError(f"hero {hero_id} has inconsistent fold cohort counts")
    if folds["train"] + folds["validation"] != selection:
        raise ArtifactError(f"hero {hero_id} has inconsistent fold cohort counts")
    return eligible, selection, folds


def _path_items(
    document: dict[str, object],
    hero_id: int,
    eligible: int,
    selection: int,
    folds: dict[str, int],
) -> tuple[tuple[ItemEvidence, ...], list[int]]:
    raw_items = object_list(document.get("items"))
    if raw_items is None:
        raise ArtifactError(f"hero {hero_id} has incomplete build evidence")
    items, item_ids = _hero_items(raw_items, hero_id, eligible)
    denominators_match = all(
        item.selection_eligible_player_matches == selection
        and item.training_eligible_player_matches == folds["train"]
        and item.validation_eligible_player_matches == folds["validation"]
        and item.test_eligible_player_matches == folds["test"]
        for item in items
    )
    if not denominators_match:
        raise ArtifactError(f"hero {hero_id} item fold denominators disagree")
    return items, item_ids


def _build_path(
    value: object,
    *,
    hero_id: int,
    hero_name: str,
) -> HeroBuildEvidence:
    document = object_dict(value)
    if document is None:
        raise ArtifactError(f"hero {hero_id} contains a malformed build path")
    path_id, path_label, signature, discovery = _path_identity(document, hero_id)
    eligible, selection, folds = _path_cohort(document, hero_id)
    items, item_ids = _path_items(document, hero_id, eligible, selection, folds)
    core_policy = _core_policy(
        document.get("core_policy"), hero_id, set(item_ids), eligible
    )
    sequence_policy = _sequence_policy(document.get("sequence_policy"), hero_id)
    situational_policy = _situational_policy(
        document.get("situational_policy"), hero_id
    )
    tier_policy = _tier_policy(document.get("tier_policy"), hero_id, items)
    validate_policy_item_references(
        core_policy,
        tier_policy,
        sequence_policy,
        situational_policy,
        items=items,
        hero_id=hero_id,
    )
    return HeroBuildEvidence(
        hero_id=hero_id,
        hero=hero_name,
        eligible_player_matches=eligible,
        selection_eligible_player_matches=selection,
        fold_eligible_player_matches=folds,
        median_final_net_worth=_required_int(
            document.get("median_final_net_worth"),
            "median final net worth",
            minimum=1,
        ),
        items=items,
        core_policy=core_policy,
        tier_policy=tier_policy,
        sequence_policy=sequence_policy,
        situational_policy=situational_policy,
        path_id=path_id,
        path_label=path_label,
        signature_item_ids=signature,
        discovery=discovery,
    )


def _hero_builds(value: object) -> tuple[int, tuple[HeroBuildEvidence, ...]]:
    document = object_dict(value)
    if document is None:
        raise ArtifactError("build evidence contains a malformed hero")
    hero_id = _required_int(document.get("hero_id"), "hero id", minimum=1)
    name = document.get("hero")
    raw_builds = object_list(document.get("builds"))
    if not isinstance(name, str) or not name.strip():
        raise ArtifactError(f"hero {hero_id} has no name")
    if not raw_builds:
        raise ArtifactError(f"hero {hero_id} has no supported build paths")
    builds = tuple(
        _build_path(build, hero_id=hero_id, hero_name=name.strip())
        for build in raw_builds
    )
    path_ids = [build.path_id for build in builds]
    if len(path_ids) != len(set(path_ids)):
        raise ArtifactError(f"hero {hero_id} contains duplicate build paths")
    return hero_id, builds
