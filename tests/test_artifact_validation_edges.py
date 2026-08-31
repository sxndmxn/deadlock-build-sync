import copy
import hashlib
import json
from pathlib import Path

import pytest

from deadlock_build_sync.artifacts import (
    ArtifactError,
    build_policy_artifact,
    load_fingerprinted_json,
    load_policy_artifact,
    validate_hero_document,
    validate_policy_artifact,
)
from deadlock_build_sync.value_validation import (
    require_object_dict,
    require_object_list,
)
from tests.artifact_bundle_fixtures import _policy


def _policy_document() -> dict[str, object]:
    return build_policy_artifact(
        [_policy("snapshot")],
        snapshot_manifest={"snapshot_id": "snapshot"},
        requested_hero_ids={12},
    )


@pytest.mark.parametrize(
    "hero",
    [7, {"hero_id": "12", "path_id": "default"}, {"hero_id": 12, "path_id": ""}],
)
def test_hero_document_rejects_malformed_build_rows(hero: object) -> None:
    with pytest.raises(ArtifactError, match="malformed hero"):
        validate_hero_document({"heroes": [hero]}, requested_hero_ids={12})


def test_hero_document_rejects_bad_evidence_containers() -> None:
    hero: dict[str, object] = {
        "hero_id": 12,
        "path_id": "default",
        "evidence_ids": "claim",
        "evidence": [],
    }

    with pytest.raises(ArtifactError, match="malformed evidence references"):
        validate_hero_document({"heroes": [hero]}, requested_hero_ids={12})


def test_hero_document_rejects_non_array_and_coverage_errors() -> None:
    with pytest.raises(ArtifactError, match="heroes must be an array"):
        validate_hero_document({"heroes": {}}, requested_hero_ids=set())
    with pytest.raises(ArtifactError, match="missing heroes"):
        validate_hero_document({"heroes": []}, requested_hero_ids={12})
    with pytest.raises(ArtifactError, match="extra heroes"):
        validate_hero_document(
            {"heroes": [{"hero_id": 13, "path_id": "default"}]},
            requested_hero_ids={12},
            allowed_exclusions={12: "unsupported"},
        )
    with pytest.raises(ArtifactError, match="exclusions need reasons"):
        validate_hero_document(
            {"heroes": []},
            requested_hero_ids={12},
            allowed_exclusions={12: " "},
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("snapshot_manifest", None),
        ("snapshot_manifest", {"snapshot_id": 7}),
        ("requested_hero_ids", None),
        ("requested_hero_ids", ["12"]),
        ("exclusions", None),
        ("policies", None),
    ],
)
def test_policy_artifact_requires_complete_header(field: str, value: object) -> None:
    document = _policy_document()
    document[field] = value

    with pytest.raises(ArtifactError, match="missing manifest or coverage data"):
        validate_policy_artifact(document)


def test_policy_artifact_rejects_schema_and_exclusion_errors() -> None:
    bad_schema = _policy_document()
    bad_schema["schema_version"] = 0
    with pytest.raises(ArtifactError, match="unsupported policy-artifact schema"):
        validate_policy_artifact(bad_schema)

    malformed = _policy_document()
    malformed["exclusions"] = [7]
    with pytest.raises(ArtifactError, match="invalid exclusion"):
        validate_policy_artifact(malformed)

    invalid = _policy_document()
    invalid["exclusions"] = [{"hero_id": 13, "reason": ""}]
    with pytest.raises(ArtifactError, match="invalid exclusion"):
        validate_policy_artifact(invalid)


def test_policy_artifact_rejects_malformed_and_invalid_policies() -> None:
    malformed = _policy_document()
    malformed["policies"] = [7]
    with pytest.raises(ArtifactError, match="malformed policy"):
        validate_policy_artifact(malformed)

    invalid = _policy_document()
    policies = require_object_list(invalid["policies"])
    policy = require_object_dict(policies[0])
    policy["nodes"] = []
    with pytest.raises(ArtifactError, match="invalid policy"):
        validate_policy_artifact(invalid)


def test_policy_artifact_rejects_duplicate_and_conflicting_coverage() -> None:
    duplicate = _policy_document()
    policies = require_object_list(duplicate["policies"])
    policies.append(copy.deepcopy(policies[0]))
    with pytest.raises(ArtifactError, match="duplicate build paths"):
        validate_policy_artifact(duplicate)

    conflict = _policy_document()
    conflict["exclusions"] = [{"hero_id": 12, "reason": "unsupported"}]
    with pytest.raises(ArtifactError, match="both includes and excludes"):
        validate_policy_artifact(conflict)

    incomplete = _policy_document()
    incomplete["requested_hero_ids"] = [12, 13]
    with pytest.raises(ArtifactError, match="does not cover requested"):
        validate_policy_artifact(incomplete)


def test_policy_artifact_loader_wraps_read_and_shape_errors(tmp_path: Path) -> None:
    missing = tmp_path / "missing.json"
    with pytest.raises(ArtifactError, match="could not read policy artifact"):
        load_policy_artifact(missing)

    path = tmp_path / "policies.json"
    path.write_text("{", encoding="utf-8")
    with pytest.raises(ArtifactError, match="could not read policy artifact"):
        load_policy_artifact(path)

    path.write_text("[]", encoding="utf-8")
    with pytest.raises(ArtifactError, match="root must be an object"):
        load_policy_artifact(path)


def test_fingerprinted_loader_wraps_read_json_and_shape_errors(tmp_path: Path) -> None:
    missing = tmp_path / "missing.json"
    with pytest.raises(ArtifactError, match="could not read artifact"):
        load_fingerprinted_json(missing, expected_sha256="0" * 64)

    invalid_json = tmp_path / "invalid.json"
    raw = b"{"
    invalid_json.write_bytes(raw)
    with pytest.raises(ArtifactError, match="could not read artifact"):
        load_fingerprinted_json(
            invalid_json,
            expected_sha256=hashlib.sha256(raw).hexdigest(),
        )

    wrong_shape = tmp_path / "array.json"
    raw = json.dumps([]).encode()
    wrong_shape.write_bytes(raw)
    with pytest.raises(ArtifactError, match="root is not an object"):
        load_fingerprinted_json(
            wrong_shape,
            expected_sha256=hashlib.sha256(raw).hexdigest(),
        )
