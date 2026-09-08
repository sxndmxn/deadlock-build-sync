"""Admit an exact artifact bundle for evaluation without Steam discovery."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from .artifact_bundle import (
    _calculate_snapshot_identity,
    _parse_hero_contexts,
    _read_document,
    _validate_bundle_evidence,
)
from .artifact_projection import _reconstruct_ability_path
from .artifacts import load_policy_artifact
from .recommendation_state import RecommendationError
from .snapshot import sha256_json
from .strategy_context import validate_strategy_context_document
from .value_validation import object_dict, object_rows

if TYPE_CHECKING:
    from pathlib import Path

    from .ability_order import AbilityPath
    from .build_evidence import BuildEvidenceCatalog
    from .policy import BuildPolicy


@dataclass(frozen=True)
class QualityInputs:
    evidence: BuildEvidenceCatalog
    policies: tuple[BuildPolicy, ...]
    abilities: dict[str, AbilityPath]
    context_sha256: str
    cutoff: int


def load_quality_inputs(directory: Path) -> QualityInputs:
    context = _read_document(directory / "strategy-context.json", "strategy context")
    validate_strategy_context_document(context)
    manifest, policies = load_policy_artifact(directory / "policies.json")
    if object_dict(context.get("snapshot_manifest")) != manifest:
        raise RecommendationError("quality artifacts use different snapshots")
    if _calculate_snapshot_identity(manifest) != manifest.get("snapshot_id"):
        raise RecommendationError("quality snapshot fingerprint does not match")
    evidence = _validate_bundle_evidence(
        directory / "build-evidence.json", context, manifest
    )
    heroes = _parse_hero_contexts(context)
    evidence_keys = {
        (hero_id, build.path_id)
        for hero_id, builds in evidence.hero_builds.items()
        for build in builds
    }
    if set(heroes) != set(policies) or set(policies) != evidence_keys:
        raise RecommendationError("quality artifacts cover different build paths")
    abilities = {}
    for key, policy in policies.items():
        if heroes[key].get("policy_id") != policy.policy_id:
            raise RecommendationError("quality context references another policy")
        path = _reconstruct_ability_path(heroes[key], policy)
        build = next(
            build
            for build in evidence.hero_builds[policy.hero_id]
            if build.path_id == policy.path_id
        )
        if (
            path.filter_item_ids
            and path.filter_item_ids != build.core_policy.backbone_item_ids
        ):
            raise RecommendationError("ability filter differs from the build backbone")
        abilities[policy.policy_id] = path
    created = datetime.fromisoformat(str(manifest.get("created_at")))
    if created.tzinfo is None:
        raise RecommendationError("frozen policy creation time must include a timezone")
    return QualityInputs(
        evidence,
        tuple(policy for _, policy in sorted(policies.items())),
        abilities,
        sha256_json(context),
        max(evidence.as_of_timestamp, int(created.timestamp())),
    )


def load_replay_assets(
    path: Path, evidence: BuildEvidenceCatalog
) -> list[dict[str, object]]:
    value = json.loads(path.read_bytes())
    assets = object_rows(value)
    if assets is None or not isinstance(value, list) or len(assets) != len(value):
        raise RecommendationError("replay assets must be a list of objects")
    normal = [
        asset
        for asset in assets
        if str(asset.get("game_mode") or "normal").casefold() == "normal"
    ]
    if sha256_json(normal) != evidence.items_sha256:
        raise RecommendationError(
            "replay assets differ from the pinned evidence assets"
        )
    return normal
