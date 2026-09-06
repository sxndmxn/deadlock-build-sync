import copy
import json
from pathlib import Path

import pytest

from deadlock_build_sync import artifact_reconstruction
from deadlock_build_sync.artifact_bundle_types import ArtifactBundleError
from deadlock_build_sync.artifacts import load_policy_artifact
from deadlock_build_sync.build_evidence import HeroBuildEvidence, load_build_evidence
from deadlock_build_sync.policy import BuildPolicy
from deadlock_build_sync.value_validation import (
    require_object_dict,
    require_object_rows,
)
from tests.artifact_bundle_fixtures import _projection, _write_bundle


def _inputs(
    root: Path,
) -> tuple[dict[str, object], BuildPolicy, HeroBuildEvidence, dict[str, object]]:
    context_path, policy_path, _, evidence_path = _write_bundle(root)
    loaded: object = json.loads(context_path.read_text(encoding="utf-8"))
    context = require_object_dict(loaded)
    hero = require_object_rows(context["heroes"])[0]
    hero["projection"] = _projection()
    manifest, policies = load_policy_artifact(policy_path)
    policy = policies[12, "default"]
    evidence = load_build_evidence(evidence_path).heroes[12]
    return hero, policy, evidence, manifest


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("hero_id", 13),
        ("path_id", "other"),
        ("hero", 7),
        ("hero", " "),
        ("hero_mechanics", []),
        ("policy_id", "wrong"),
        ("snapshot_id", "wrong"),
    ],
)
def test_reconstruction_rejects_inconsistent_hero_identity(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    hero, policy, _, _ = _inputs(tmp_path)
    hero[field] = value

    with pytest.raises(ArtifactBundleError, match="inconsistent identity"):
        artifact_reconstruction._hero_identity(hero, policy)


def test_reconstruction_requires_a_nonempty_hero_class(tmp_path: Path) -> None:
    hero, policy, _, _ = _inputs(tmp_path)
    mechanics = require_object_dict(hero["hero_mechanics"])
    mechanics["class_name"] = ""

    with pytest.raises(ArtifactBundleError, match="inconsistent identity"):
        artifact_reconstruction._hero_identity(hero, policy)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("core", None, "no core evidence"),
        ("joint_player_matches", 0, "invalid core evidence"),
        ("joint_share", "0.1", "invalid core evidence"),
        ("joint_share", 0.0, "invalid core evidence"),
        ("joint_share", 1.1, "invalid core evidence"),
        ("median_final_net_worth", 0, "invalid core evidence"),
        ("core_target_cost", 0, "invalid core evidence"),
        ("core_target_cost", 40_000, "invalid core evidence"),
    ],
)
def test_reconstruction_rejects_invalid_core_summary(
    tmp_path: Path,
    field: str,
    value: object,
    message: str,
) -> None:
    hero, policy, _, _ = _inputs(tmp_path)
    if field == "core":
        hero[field] = value
    else:
        require_object_dict(hero["core"])[field] = value

    with pytest.raises(ArtifactBundleError, match=message):
        artifact_reconstruction._core_evidence(hero, policy)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("tag_ids", None),
        ("tag_ids", [10, 10, 3]),
        ("tag_ids", [True, 1005, 3]),
        ("tag_classes", ["ability_10", "item_1005", ""]),
        ("tag_labels", ["Ability", "Item"]),
        ("tag_catalog_sha256", "wrong"),
        ("archetype", ""),
    ],
)
def test_reconstruction_rejects_invalid_build_identity_fields(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    hero, policy, _, manifest = _inputs(tmp_path)
    projection = require_object_dict(hero["projection"])
    build = require_object_dict(projection["build"])
    build[field] = value

    with pytest.raises(ArtifactBundleError, match="invalid build tags"):
        artifact_reconstruction._build_identity(hero, policy, manifest)


def test_reconstruction_rejects_missing_projection_and_bad_function_tag(
    tmp_path: Path,
) -> None:
    hero, policy, _, manifest = _inputs(tmp_path)
    missing = copy.deepcopy(hero)
    missing["projection"] = None
    with pytest.raises(ArtifactBundleError, match="no build identity"):
        artifact_reconstruction._build_identity(missing, policy, manifest)

    bad_class = copy.deepcopy(hero)
    projection = require_object_dict(bad_class["projection"])
    build = require_object_dict(projection["build"])
    build["tag_classes"] = ["ability_10", "item_1005", "not-a-function"]
    with pytest.raises(ArtifactBundleError, match="invalid build tags"):
        artifact_reconstruction._build_identity(bad_class, policy, manifest)


def test_reconstruction_rejects_incomplete_epoch_boundaries(tmp_path: Path) -> None:
    _, _, _, manifest = _inputs(tmp_path)
    epochs = require_object_dict(manifest["epochs"])
    epochs.pop("telemetry")

    with pytest.raises(ArtifactBundleError, match="invalid epoch boundaries"):
        artifact_reconstruction._analysis_start_timestamp(manifest)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("client_version", "123"),
        ("match_mode", 7),
        ("as_of_timestamp", "200"),
    ],
)
def test_reconstruction_rejects_invalid_snapshot_cohort(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    hero, policy, evidence, manifest = _inputs(tmp_path)
    manifest[field] = value

    with pytest.raises(ArtifactBundleError, match="invalid cohort"):
        artifact_reconstruction._guide(
            hero,
            policy,
            evidence,
            manifest=manifest,
            rank_identity="Rank 7–11",
        )
