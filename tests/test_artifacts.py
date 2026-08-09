import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

import deadlock_build_sync.artifacts as artifact_module
from deadlock_build_sync.artifacts import (
    ArtifactCompatibility,
    ArtifactError,
    FingerprintLayers,
    atomic_write_bytes,
    build_policy_artifact,
    load_fingerprinted_json,
    validate_hero_document,
    validate_policy_artifact,
)
from deadlock_build_sync.policy import BuildPolicy, NodeKind, PolicyNode


def compatibility(**changes: object) -> ArtifactCompatibility:
    base = ArtifactCompatibility(
        schema_version=1,
        hero_id=12,
        snapshot_id="snapshot",
        client_version=123,
        match_mode="ranked",
        rank_labels_sha256="ranks",
        mechanics_sha256="mechanics",
        analytics_sha256="analytics",
        policy_basis_sha256="policy",
        prompt_version=15,
        model="model",
    )
    return replace(base, **changes)


def test_fingerprint_layers_invalidate_only_their_downstream_dependencies() -> None:
    original = FingerprintLayers.calculate(
        mechanics={"damage": 10},
        analytics={"count": 100},
        policy_basis={"guard": "default"},
        narrative={"text": "explain"},
        projection={"optional": True},
    )
    narrative_changed = FingerprintLayers.calculate(
        mechanics={"damage": 10},
        analytics={"count": 100},
        policy_basis={"guard": "default"},
        narrative={"text": "changed"},
        projection={"optional": True},
    )
    mechanics_changed = FingerprintLayers.calculate(
        mechanics={"damage": 11},
        analytics={"count": 100},
        policy_basis={"guard": "default"},
        narrative={"text": "explain"},
        projection={"optional": True},
    )

    assert original.mechanics == narrative_changed.mechanics
    assert original.analytics == narrative_changed.analytics
    assert original.policy_basis == narrative_changed.policy_basis
    assert original.narrative != narrative_changed.narrative
    assert original.projection == narrative_changed.projection
    assert original.as_dict().keys() == mechanics_changed.as_dict().keys()
    assert all(
        original.as_dict()[key] != mechanics_changed.as_dict()[key]
        for key in original.as_dict()
    )


def test_exact_artifact_compatibility_rejects_mode_and_prompt_changes() -> None:
    actual = compatibility()
    actual.assert_reusable_with(compatibility())

    with pytest.raises(ArtifactError, match="match_mode, prompt_version"):
        actual.assert_reusable_with(
            compatibility(match_mode="unranked", prompt_version=16)
        )


def test_document_completeness_rejects_missing_duplicates_and_dangling_refs() -> None:
    valid = {
        "heroes": [
            {
                "hero_id": 12,
                "evidence_ids": ["claim/1"],
                "evidence": [{"claim_id": "claim/1"}],
            }
        ]
    }
    validate_hero_document(valid, requested_hero_ids={12})
    validate_hero_document(
        {"heroes": []},
        requested_hero_ids={12},
        allowed_exclusions={12: "insufficient support"},
    )
    with pytest.raises(ArtifactError, match="dangling"):
        validate_hero_document(
            {"heroes": [{"hero_id": 12, "evidence_ids": ["missing"], "evidence": []}]},
            requested_hero_ids={12},
        )
    with pytest.raises(ArtifactError, match="duplicate"):
        validate_hero_document(
            {"heroes": [valid["heroes"][0], valid["heroes"][0]]},
            requested_hero_ids={12},
        )


def test_policy_sidecar_binds_snapshot_and_complete_roster() -> None:
    policy = BuildPolicy(
        schema_version=1,
        hero_id=12,
        variant="fixture",
        invariant_kit_id="kit",
        strategic_role="fixture role",
        snapshot_id="snapshot",
        entry="end",
        nodes=(PolicyNode("end", NodeKind.END),),
        evidence=(),
    )
    document = build_policy_artifact(
        [policy],
        snapshot_manifest={"snapshot_id": "snapshot", "client_version": 123},
        requested_hero_ids={12, 13},
        exclusions=((13, "incomplete mechanics"),),
    )

    validate_policy_artifact(document)
    assert document["policies"][0]["policy_id"] == policy.policy_id
    assert document["exclusions"] == [{"hero_id": 13, "reason": "incomplete mechanics"}]

    document["snapshot_manifest"]["snapshot_id"] = "changed"
    with pytest.raises(ArtifactError, match="another snapshot"):
        validate_policy_artifact(document)


def test_atomic_write_preserves_old_file_when_file_fsync_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "artifact.json"
    target.write_bytes(b"old")

    def fail_fsync(_descriptor: int) -> None:
        raise OSError("injected file fsync failure")

    monkeypatch.setattr(artifact_module.os, "fsync", fail_fsync)
    with pytest.raises(OSError, match="injected"):
        atomic_write_bytes(target, b"new")

    assert target.read_bytes() == b"old"
    assert not list(tmp_path.glob(".artifact.json.*.tmp"))


def test_atomic_write_leaves_a_complete_new_file_when_directory_fsync_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "artifact.json"
    target.write_bytes(b"old")
    real_fsync = artifact_module.os.fsync
    calls = 0

    def fail_directory_fsync(descriptor: int) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected directory fsync failure")
        real_fsync(descriptor)

    monkeypatch.setattr(artifact_module.os, "fsync", fail_directory_fsync)
    with pytest.raises(OSError, match="directory"):
        atomic_write_bytes(target, b"complete-new")

    assert target.read_bytes() == b"complete-new"


def test_load_fingerprinted_json_checks_exact_bytes(tmp_path: Path) -> None:
    target = tmp_path / "artifact.json"
    raw = b'{"value": 1}\n'
    target.write_bytes(raw)

    assert load_fingerprinted_json(
        target,
        expected_sha256=hashlib.sha256(raw).hexdigest(),
    ) == {"value": 1}
    with pytest.raises(ArtifactError, match="digest mismatch"):
        load_fingerprinted_json(target, expected_sha256="0" * 64)
