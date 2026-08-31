from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from deadlock_build_sync import artifact_bundle as bundle
from deadlock_build_sync.artifact_bundle_types import ArtifactBundleError
from deadlock_build_sync.build_evidence import (
    BuildEvidenceCatalog,
    load_build_evidence,
)
from deadlock_build_sync.narratives import NarrativeCatalog, load_narrative_catalog
from deadlock_build_sync.value_validation import object_dict, object_list
from tests.artifact_bundle_fixtures import _policy, _write_bundle

if TYPE_CHECKING:
    from pathlib import Path

    from deadlock_build_sync.policy import BuildPolicy


def _inputs(
    tmp_path: Path,
) -> tuple[
    dict[str, object],
    dict[str, object],
    NarrativeCatalog,
    BuildEvidenceCatalog,
]:
    context_path, policy_path, narrative_path, evidence_path = _write_bundle(tmp_path)
    context = object_dict(json.loads(context_path.read_text(encoding="utf-8")))
    policies = object_dict(json.loads(policy_path.read_text(encoding="utf-8")))
    assert context is not None
    assert policies is not None
    return (
        context,
        policies,
        load_narrative_catalog(narrative_path),
        load_build_evidence(evidence_path),
    )


def _manifest(context: dict[str, object]) -> dict[str, object]:
    manifest = object_dict(context["snapshot_manifest"])
    assert manifest is not None
    return manifest


def test_read_document_wraps_file_and_json_errors(tmp_path: Path) -> None:
    missing = tmp_path / "missing.json"
    with pytest.raises(ArtifactBundleError, match="could not read context"):
        bundle._read_document(missing, "context")

    invalid = tmp_path / "invalid.json"
    invalid.write_text("{", encoding="utf-8")
    with pytest.raises(ArtifactBundleError, match="could not read context"):
        bundle._read_document(invalid, "context")

    invalid.write_text("[]", encoding="utf-8")
    with pytest.raises(ArtifactBundleError, match="root must be an object"):
        bundle._read_document(invalid, "context")


def test_snapshot_identity_rejects_empty_and_malformed_records(
    tmp_path: Path,
) -> None:
    context, _policies, _catalog, _evidence = _inputs(tmp_path)
    manifest = _manifest(context)
    assert len(bundle._snapshot_identity(manifest)) == 64

    empty = deepcopy(manifest)
    empty["records"] = []
    with pytest.raises(ArtifactBundleError, match="no source records"):
        bundle._snapshot_identity(empty)

    malformed = deepcopy(manifest)
    malformed["records"] = [1]
    with pytest.raises(ArtifactBundleError, match="no source records"):
        bundle._snapshot_identity(malformed)


def test_patch_rejects_missing_malformed_and_wrong_identity(tmp_path: Path) -> None:
    context, _policies, _catalog, _evidence = _inputs(tmp_path)
    with pytest.raises(ArtifactBundleError, match="no patch identity"):
        bundle._patch(None)
    with pytest.raises(ArtifactBundleError, match="malformed patch"):
        bundle._patch({"title": "Patch"})

    patch = deepcopy(object_dict(context["patch"]))
    assert patch is not None
    patch["identity"] = "wrong"
    with pytest.raises(ArtifactBundleError, match="fingerprint"):
        bundle._patch(patch)


def test_rank_and_exclusion_decoders_reject_bad_values() -> None:
    with pytest.raises(ArtifactBundleError, match="no numeric minimum rank"):
        bundle._rank_from_boundary({}, "minimum")
    with pytest.raises(ArtifactBundleError, match="invalid minimum rank"):
        bundle._rank_from_boundary({"badge_id": 70}, "minimum")
    with pytest.raises(ArtifactBundleError, match="no rank range"):
        bundle._rank_range(None)
    with pytest.raises(ArtifactBundleError, match="invalid exclusions"):
        bundle._exclusions(None)
    with pytest.raises(ArtifactBundleError, match="malformed exclusion"):
        bundle._exclusions([1])
    with pytest.raises(ArtifactBundleError, match="malformed exclusion"):
        bundle._exclusions([{"hero_id": 12, "reason": " "}])
    assert bundle._exclusions([{"hero_id": 12, "reason": " skipped "}]) == (
        (12, "skipped"),
    )


def test_validated_manifest_checks_each_shared_identity(tmp_path: Path) -> None:
    context, policies, catalog, _evidence = _inputs(tmp_path)
    with pytest.raises(ArtifactBundleError, match="no snapshot manifest"):
        bundle._validated_manifest({}, policies, catalog)

    crossed = deepcopy(policies)
    crossed["snapshot_manifest"] = {}
    with pytest.raises(ArtifactBundleError, match="manifests differ"):
        bundle._validated_manifest(context, crossed, catalog)

    changed_context = deepcopy(context)
    changed_manifest = _manifest(changed_context)
    changed_manifest["snapshot_id"] = "0" * 64
    changed_policies = deepcopy(policies)
    changed_policies["snapshot_manifest"] = changed_manifest
    with pytest.raises(ArtifactBundleError, match="snapshot fingerprint"):
        bundle._validated_manifest(changed_context, changed_policies, catalog)

    with pytest.raises(ArtifactBundleError, match="another artifact snapshot"):
        bundle._validated_manifest(
            context,
            policies,
            replace(catalog, snapshot_id="0" * 64),
        )
    with pytest.raises(ArtifactBundleError, match="another strategy context"):
        bundle._validated_manifest(
            context,
            policies,
            replace(catalog, source_context_sha256="0" * 64),
        )


def test_validated_coverage_checks_requests_and_exclusions(tmp_path: Path) -> None:
    context, policies, catalog, _evidence = _inputs(tmp_path)
    with pytest.raises(ArtifactBundleError, match="invalid requested heroes"):
        bundle._validated_coverage(
            {**context, "requested_hero_ids": ["12"]}, policies, catalog
        )
    with pytest.raises(ArtifactBundleError, match="coverage differs"):
        bundle._validated_coverage(
            context,
            {**policies, "requested_hero_ids": [13]},
            catalog,
        )
    with pytest.raises(ArtifactBundleError, match="coverage differs"):
        bundle._validated_coverage(
            context,
            {**policies, "exclusions": [{"hero_id": 13, "reason": "skip"}]},
            catalog,
        )
    with pytest.raises(ArtifactBundleError, match="coverage differs"):
        bundle._validated_coverage(
            context,
            policies,
            replace(catalog, requested_hero_ids=frozenset({13})),
        )
    with pytest.raises(ArtifactBundleError, match="coverage differs"):
        bundle._validated_coverage(
            context,
            policies,
            replace(catalog, exclusions={12: "skip"}),
        )


def test_validated_cohort_checks_patch_modes_and_client(tmp_path: Path) -> None:
    context, _policies, catalog, _evidence = _inputs(tmp_path)
    manifest = _manifest(context)

    with pytest.raises(ArtifactBundleError, match="patch differs"):
        bundle._validated_cohort(context, {**manifest, "patch": {}}, catalog)
    with pytest.raises(ArtifactBundleError, match="another patch"):
        bundle._validated_cohort(
            context,
            manifest,
            replace(catalog, patch_identity="wrong"),
        )
    with pytest.raises(ArtifactBundleError, match="normal ruleset"):
        bundle._validated_cohort(context, {**manifest, "game_mode": "ranked"}, catalog)
    with pytest.raises(ArtifactBundleError, match="narrative cohort differs"):
        bundle._validated_cohort(
            context,
            manifest,
            replace(catalog, client_version=999),
        )
    with pytest.raises(ArtifactBundleError, match="narrative cohort differs"):
        bundle._validated_cohort(
            context,
            manifest,
            replace(catalog, match_mode="unranked"),
        )


def test_validated_cohort_checks_rank_label_data(tmp_path: Path) -> None:
    context, _policies, catalog, _evidence = _inputs(tmp_path)
    manifest = _manifest(context)
    with pytest.raises(ArtifactBundleError, match="no rank range"):
        bundle._validated_cohort(context, {**manifest, "rank_range": None}, catalog)

    rank = deepcopy(object_dict(manifest["rank_range"]))
    assert rank is not None
    rank["label"] = 1
    with pytest.raises(ArtifactBundleError, match="no rank label"):
        bundle._validated_cohort(context, {**manifest, "rank_range": rank}, catalog)

    rank["label"] = "Oracle"
    rank["labels_sha256"] = "wrong"
    with pytest.raises(ArtifactBundleError, match="rank labels differ"):
        bundle._validated_cohort(context, {**manifest, "rank_range": rank}, catalog)


def test_policy_and_hero_decoders_skip_malformed_rows(tmp_path: Path) -> None:
    context, policies, _catalog, _evidence = _inputs(tmp_path)
    decoded = bundle._decoded_policies(policies)
    assert set(decoded) == {(12, "default")}
    assert bundle._decoded_policies({}) == {}

    heroes = bundle._hero_contexts(context)
    assert set(heroes) == {(12, "default")}
    assert bundle._hero_contexts({"heroes": [{"hero_id": "12"}, 1]}) == {}


def test_evidence_snapshot_record_checks_count_and_metadata(tmp_path: Path) -> None:
    context, _policies, _catalog, evidence = _inputs(tmp_path)
    manifest = _manifest(context)
    assert bundle._evidence_snapshot_record(manifest, evidence)["path"] == (
        "artifact:build-evidence"
    )

    without = deepcopy(manifest)
    without["records"] = []
    with pytest.raises(ArtifactBundleError, match="one build-evidence record"):
        bundle._evidence_snapshot_record(without, evidence)

    malformed = deepcopy(manifest)
    records = object_list(malformed["records"])
    assert records is not None
    record = object_dict(records[1])
    assert record is not None
    record["parameters"] = None
    records[1] = record
    malformed["records"] = records
    with pytest.raises(ArtifactBundleError, match="differs from"):
        bundle._evidence_snapshot_record(malformed, evidence)


def test_build_evidence_compatibility_reports_every_missing_identity(
    tmp_path: Path,
) -> None:
    _context, _policies, _catalog, evidence = _inputs(tmp_path)
    checks = bundle._build_evidence_compatibility(evidence, {}, {})

    assert checks
    assert not any(checks.values())


def test_validated_build_evidence_wraps_loader_error(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid.json"
    invalid.write_text("{}", encoding="utf-8")
    with pytest.raises(ArtifactBundleError):
        bundle._validated_build_evidence(invalid, {}, {})


def test_reconstruct_guides_rejects_path_missing_from_evidence(tmp_path: Path) -> None:
    context, _policies, catalog, evidence = _inputs(tmp_path)
    manifest = _manifest(context)
    policy: BuildPolicy = _policy(str(manifest["snapshot_id"]))
    patch, _rank_range, rank_identity = bundle._validated_cohort(
        context,
        manifest,
        catalog,
    )
    key = (12, "missing")
    with pytest.raises(ArtifactBundleError, match="lacks path"):
        bundle._reconstruct_guides(
            {key: {}},
            {key: policy},
            evidence,
            bundle._GuideReconstructionContext(
                manifest,
                rank_identity,
                patch,
                catalog,
            ),
        )
