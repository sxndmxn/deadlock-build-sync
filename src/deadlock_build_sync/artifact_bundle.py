from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast

from .api import Patch
from .artifacts import ArtifactError, validate_policy_artifact
from .build_evidence import (
    BuildEvidenceCatalog,
    evidence_record_sha256,
    load_build_evidence,
)
from .narratives import apply_narrative, load_narrative_catalog
from .policy import BuildPolicy
from .ranks import Rank, RankDivision, RankRange, RankTier
from .snapshot import sha256_json
from .strategy_context import validate_strategy_context_document
from .value_validation import integer, object_dict, object_list, object_rows

if TYPE_CHECKING:
    from pathlib import Path

    from .narratives import NarrativeCatalog
    from .purchase_guide import PurchaseGuide


from .artifact_bundle_types import (
    _COVERAGE_MISMATCH,
    ArtifactBuildIdentity,
    ArtifactBundleError,
    ArtifactGuideBundle,
    _GuideReconstructionContext,
)
from .artifact_projection import _policy_core
from .artifact_reconstruction import _guide

__all__ = [
    "ArtifactBuildIdentity",
    "ArtifactBundleError",
    "ArtifactGuideBundle",
    "_policy_core",
    "load_artifact_guide_bundle",
]


def _read_document(path: Path, label: str) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ArtifactBundleError(f"could not read {label} {path}: {error}") from error
    if not isinstance(value, dict):
        raise ArtifactBundleError(f"{label} root must be an object: {path}")
    return value


def _snapshot_identity(manifest: dict[str, object]) -> str:
    payload = dict(manifest)
    payload.pop("snapshot_id", None)
    payload.pop("created_at", None)
    raw_records = object_list(payload.get("records"))
    records = object_rows(payload.get("records"))
    if not raw_records or records is None or len(records) != len(raw_records):
        raise ArtifactBundleError("artifact snapshot has no source records")
    stable_records: list[dict[str, object]] = []
    for record in records:
        stable = dict(record)
        stable.pop("fetched_at", None)
        stable_records.append(stable)
    payload["records"] = stable_records
    return sha256_json(payload)


def _patch(value: object) -> Patch:
    document = object_dict(value)
    if document is None:
        raise ArtifactBundleError("artifact bundle has no patch identity")
    data = document
    try:
        patch = Patch(
            title=str(data["title"]),
            start_timestamp=integer(data["start_timestamp"]),
            published_at=str(data["published_at"]),
            source=str(data["source"]),
            guid=str(data["guid"]),
            link=str(data["link"]),
            content_sha256=str(data["content_sha256"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ArtifactBundleError(
            f"artifact bundle has a malformed patch: {error}"
        ) from error
    if data.get("identity") != patch.identity:
        raise ArtifactBundleError(
            "artifact patch fingerprint does not match its contents"
        )
    return patch


def _rank_from_boundary(value: object, label: str) -> Rank:
    if not isinstance(value, dict) or not isinstance(value.get("badge_id"), int):
        raise ArtifactBundleError(f"artifact bundle has no numeric {label} rank")
    data = cast("dict[str, object]", value)
    badge_id = cast("int", data["badge_id"])
    tier, division = divmod(badge_id, 10)
    try:
        rank = Rank(RankTier(tier), RankDivision(division))
    except ValueError as error:
        raise ArtifactBundleError(
            f"artifact bundle has an invalid {label} rank"
        ) from error
    return rank


def _rank_range(value: object) -> RankRange:
    if not isinstance(value, dict):
        raise ArtifactBundleError("artifact bundle has no rank range")
    return RankRange(
        _rank_from_boundary(value.get("minimum"), "minimum"),
        _rank_from_boundary(value.get("maximum"), "maximum"),
    )


def _exclusions(value: object) -> tuple[tuple[int, str], ...]:
    if not isinstance(value, list):
        raise ArtifactBundleError("artifact bundle has invalid exclusions")
    result: list[tuple[int, str]] = []
    for row in value:
        if not isinstance(row, dict):
            raise ArtifactBundleError("artifact bundle has a malformed exclusion")
        hero_id = row.get("hero_id")
        reason = row.get("reason")
        if (
            not isinstance(hero_id, int)
            or not isinstance(reason, str)
            or not reason.strip()
        ):
            raise ArtifactBundleError("artifact bundle has a malformed exclusion")
        result.append((hero_id, reason.strip()))
    return tuple(result)


def _validated_manifest(
    context: dict[str, object],
    policies: dict[str, object],
    catalog: NarrativeCatalog,
) -> dict[str, object]:
    manifest = object_dict(context.get("snapshot_manifest"))
    if manifest is None:
        raise ArtifactBundleError("strategy context has no snapshot manifest")
    data = manifest
    if policies.get("snapshot_manifest") != data:
        raise ArtifactBundleError("context and policy snapshot manifests differ")
    snapshot_id = data.get("snapshot_id")
    if snapshot_id != _snapshot_identity(data):
        raise ArtifactBundleError(
            "artifact snapshot fingerprint does not match its sources"
        )
    if catalog.snapshot_id != snapshot_id:
        raise ArtifactBundleError("narratives use another artifact snapshot")
    if catalog.source_context_sha256 != context.get("source_context_sha256"):
        raise ArtifactBundleError("narratives use another strategy context")
    return data


def _validated_coverage(
    context: dict[str, object],
    policies: dict[str, object],
    catalog: NarrativeCatalog,
) -> tuple[tuple[int, str], ...]:
    requested = context.get("requested_hero_ids")
    exclusions = _exclusions(context.get("exclusions"))
    if not isinstance(requested, list) or not all(
        isinstance(hero_id, int) for hero_id in requested
    ):
        raise ArtifactBundleError("artifact bundle has invalid requested heroes")
    if requested != policies.get("requested_hero_ids"):
        raise ArtifactBundleError(_COVERAGE_MISMATCH)
    if context.get("exclusions") != policies.get("exclusions"):
        raise ArtifactBundleError(_COVERAGE_MISMATCH)
    if catalog.requested_hero_ids != frozenset(requested):
        raise ArtifactBundleError(_COVERAGE_MISMATCH)
    if catalog.exclusions != dict(exclusions):
        raise ArtifactBundleError(_COVERAGE_MISMATCH)
    return exclusions


def _validated_cohort(
    context: dict[str, object],
    manifest: dict[str, object],
    catalog: NarrativeCatalog,
) -> tuple[Patch, RankRange, str]:
    patch = _patch(context.get("patch"))
    if manifest.get("patch") != context.get("patch"):
        raise ArtifactBundleError("artifact patch differs from its snapshot manifest")
    if catalog.patch_identity != patch.identity:
        raise ArtifactBundleError("narratives use another patch")
    if manifest.get("game_mode") != "normal" or catalog.game_mode != "normal":
        raise ArtifactBundleError("artifact bundle is not for the normal ruleset")
    if catalog.client_version != manifest.get("client_version"):
        raise ArtifactBundleError("narrative cohort differs from the artifact snapshot")
    if catalog.match_mode != manifest.get("match_mode"):
        raise ArtifactBundleError("narrative cohort differs from the artifact snapshot")
    rank_data = object_dict(manifest.get("rank_range"))
    rank_range = _rank_range(rank_data)
    if rank_data is None or not isinstance(rank_data.get("label"), str):
        raise ArtifactBundleError("artifact bundle has no rank label")
    if rank_data.get("labels_sha256") != manifest.get("rank_labels_sha256"):
        raise ArtifactBundleError("artifact rank labels differ from its snapshot")
    return patch, rank_range, str(rank_data["label"])


def _decoded_policies(
    document: dict[str, object],
) -> dict[tuple[int, str], BuildPolicy]:
    rows = object_rows(document.get("policies")) or []
    decoded = [BuildPolicy.from_dict(row) for row in rows]
    return {(policy.hero_id, policy.path_id): policy for policy in decoded}


def _hero_contexts(
    document: dict[str, object],
) -> dict[tuple[int, str], dict[str, object]]:
    rows = object_rows(document.get("heroes")) or []
    heroes: dict[tuple[int, str], dict[str, object]] = {}
    for row in rows:
        hero = row
        hero_id = hero.get("hero_id")
        path_id = hero.get("path_id")
        if isinstance(hero_id, int) and isinstance(path_id, str):
            heroes[hero_id, path_id] = hero
    return heroes


def _evidence_snapshot_record(
    manifest: dict[str, object],
    catalog: BuildEvidenceCatalog,
) -> dict[str, object]:
    records = object_rows(manifest.get("records")) or []
    evidence_records = [
        record for record in records if record.get("path") == "artifact:build-evidence"
    ]
    if len(evidence_records) != 1:
        raise ArtifactBundleError(
            "artifact snapshot must contain one build-evidence record"
        )
    record = evidence_records[0]
    parameters = object_dict(record.get("parameters"))
    if (
        parameters is None
        or parameters.get("artifact_id") != catalog.artifact_id
        or record.get("sha256") != evidence_record_sha256(catalog)
        or record.get("byte_count") != len(catalog.raw_bytes)
    ):
        raise ArtifactBundleError("build evidence differs from the artifact snapshot")
    return record


def _build_evidence_compatibility(
    catalog: BuildEvidenceCatalog,
    context: dict[str, object],
    manifest: dict[str, object],
) -> dict[str, bool]:
    requested = context.get("requested_hero_ids")
    rank = object_dict(manifest.get("rank_range"))
    patch = object_dict(manifest.get("patch")) or {}
    minimum_rank = object_dict(rank.get("minimum")) if rank is not None else None
    maximum_rank = object_dict(rank.get("maximum")) if rank is not None else None
    requested_ids = object_list(requested)
    cohort = catalog.cohort
    return {
        "client version": catalog.client_version == manifest.get("client_version"),
        "patch": catalog.patch.get("identity") == patch.get("identity"),
        "as-of cutoff": catalog.as_of_timestamp == manifest.get("as_of_timestamp"),
        "match mode": str(cohort.get("match_mode") or "").casefold()
        == str(manifest.get("match_mode") or "").casefold(),
        "game mode": str(cohort.get("game_mode") or "").casefold()
        == str(manifest.get("game_mode") or "").casefold(),
        "minimum rank": minimum_rank is not None
        and cohort.get("minimum_badge") == minimum_rank.get("badge_id"),
        "maximum rank": maximum_rank is not None
        and cohort.get("maximum_badge") == maximum_rank.get("badge_id"),
        "rank labels": catalog.rank_labels_sha256 == manifest.get("rank_labels_sha256"),
        "epochs": catalog.epochs.as_dict() == manifest.get("epochs"),
        "hero coverage": requested_ids is not None
        and catalog.requested_hero_ids
        == frozenset(value for value in requested_ids if isinstance(value, int)),
    }


def _validated_build_evidence(
    path: Path,
    context: dict[str, object],
    manifest: dict[str, object],
) -> BuildEvidenceCatalog:
    try:
        catalog = load_build_evidence(path)
    except ArtifactError as error:
        raise ArtifactBundleError(str(error)) from error
    _evidence_snapshot_record(manifest, catalog)
    checks = _build_evidence_compatibility(catalog, context, manifest)
    differences = [label for label, compatible in checks.items() if not compatible]
    if differences:
        raise ArtifactBundleError(
            "build evidence is incompatible with the reviewed bundle in: "
            + ", ".join(differences)
        )
    return catalog


def _reconstruct_guides(
    heroes: dict[tuple[int, str], dict[str, object]],
    policies: dict[tuple[int, str], BuildPolicy],
    build_evidence: BuildEvidenceCatalog,
    context: _GuideReconstructionContext,
) -> list[PurchaseGuide]:
    guides = []
    for hero_id, path_id in sorted(heroes):
        build_key = hero_id, path_id
        evidence = next(
            (
                build
                for build in build_evidence.hero_builds.get(hero_id, ())
                if build.path_id == path_id
            ),
            None,
        )
        if evidence is None:
            raise ArtifactBundleError(f"build evidence lacks path {hero_id}/{path_id}")
        guide = _guide(
            heroes[build_key],
            policies[build_key],
            evidence,
            manifest=context.manifest,
            rank_identity=evidence.cohort.rank_range.label
            if evidence.cohort
            else context.rank_identity,
            assets=list(build_evidence.assets),
        )
        guides.append(
            apply_narrative(
                guide,
                heroes[build_key],
                context.patch,
                context.narratives,
            )
        )
    return guides


def load_artifact_guide_bundle(
    context_path: Path,
    policy_path: Path,
    narrative_path: Path,
    build_evidence_path: Path,
) -> ArtifactGuideBundle:
    """Load one fully reviewed guide bundle without re-fetching analytics.

    Returns:
        Installable guides whose context, policy, narrative, and projection identities
        are exact matches.

    Raises:
        ArtifactBundleError: If any artifact is malformed, edited, stale, or crossed.

    """
    context = _read_document(context_path, "strategy context")
    policies = _read_document(policy_path, "policy artifact")
    validate_strategy_context_document(context)
    validate_policy_artifact(policies)
    catalog = load_narrative_catalog(narrative_path)

    manifest = _validated_manifest(context, policies, catalog)
    exclusions = _validated_coverage(context, policies, catalog)
    patch, rank_range, rank_identity = _validated_cohort(context, manifest, catalog)
    build_evidence = _validated_build_evidence(
        build_evidence_path,
        context,
        manifest,
    )
    if dict(exclusions) != build_evidence.exclusions:
        raise ArtifactBundleError("Artifact exclusions differ from build evidence")
    by_policy = _decoded_policies(policies)
    heroes = _hero_contexts(context)
    if set(heroes) != set(by_policy):
        raise ArtifactBundleError(
            "strategy contexts and policies cover different heroes"
        )
    admitted_identities = {
        (hero_id, build.path_id)
        for hero_id, builds in build_evidence.hero_builds.items()
        for build in builds
    }
    if set(heroes) != admitted_identities:
        raise ArtifactBundleError(
            "Artifact bundle does not contain every admitted build identity"
        )

    guides = _reconstruct_guides(
        heroes,
        by_policy,
        build_evidence,
        _GuideReconstructionContext(manifest, rank_identity, patch, catalog),
    )
    return ArtifactGuideBundle(
        guides=guides,
        snapshot_manifest=manifest,
        patch=patch,
        rank_range=rank_range,
        expected_hero_ids=frozenset(build_key[0] for build_key in heroes),
        exclusions=exclusions,
    )
