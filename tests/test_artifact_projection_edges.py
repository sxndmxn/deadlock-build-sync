from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
from typing import TYPE_CHECKING, cast

import pytest

from deadlock_build_sync import artifact_projection as projection
from deadlock_build_sync.artifact_bundle_types import ArtifactBundleError
from deadlock_build_sync.build_evidence import HeroBuildEvidence, load_build_evidence
from deadlock_build_sync.value_validation import object_dict, require_object_rows
from tests.artifact_bundle_fixtures import _policy, _projection, _write_bundle

if TYPE_CHECKING:
    from pathlib import Path

    from deadlock_build_sync.policy import BuildPolicy


def _inputs(
    tmp_path: Path,
) -> tuple[dict[str, object], BuildPolicy, HeroBuildEvidence]:
    context_path, _policy_path, _narrative_path, evidence_path = _write_bundle(tmp_path)
    context = object_dict(json.loads(context_path.read_text(encoding="utf-8")))
    assert context is not None
    hero = require_object_rows(context["heroes"])[0]
    hero["projection"] = _projection()
    catalog = load_build_evidence(evidence_path)
    evidence = catalog.hero_builds[12][0]
    return hero, _policy(str(hero["snapshot_id"])), evidence


def test_ability_projection_rejects_bad_steps_and_policy_difference(
    tmp_path: Path,
) -> None:
    hero, policy, _evidence = _inputs(tmp_path)
    ability = object_dict(hero["ability_policy"])
    assert ability is not None
    with pytest.raises(ArtifactBundleError, match="16 actions"):
        projection._ability_projection({"steps": []}, policy)

    malformed = deepcopy(ability)
    malformed_steps = require_object_rows(malformed["steps"])
    malformed_steps[0]["decision_reached_support"] = 0
    with pytest.raises(ArtifactBundleError, match="malformed ability action"):
        projection._ability_projection(malformed, policy)

    incomplete = deepcopy(ability)
    incomplete_steps = require_object_rows(incomplete["steps"])
    incomplete_steps[0]["ability_id"] = 20
    with pytest.raises(ArtifactBundleError, match="complete four-rank path"):
        projection._ability_projection(incomplete, policy)

    different = replace(
        policy,
        ability_plan=tuple(reversed(policy.ability_plan)),
    )
    with pytest.raises(ArtifactBundleError, match="differs from its policy"):
        projection._ability_projection(ability, different)


def test_ability_path_rejects_missing_and_invalid_support(tmp_path: Path) -> None:
    hero, policy, _evidence = _inputs(tmp_path)
    with pytest.raises(ArtifactBundleError, match="has no ability policy"):
        projection._ability_path({}, policy)

    invalid_type = deepcopy(hero)
    invalid_ability = deepcopy(cast("dict[str, object]", hero["ability_policy"]))
    invalid_ability["final_branch_support"] = "100"
    invalid_type["ability_policy"] = invalid_ability
    with pytest.raises(ArtifactBundleError, match="invalid support"):
        projection._ability_path(invalid_type, policy)

    for field, value in (
        ("final_branch_support", 0),
        ("complete_path_appearances", 300),
        ("observed_final_branch_outcome_rate", 2.0),
    ):
        invalid = deepcopy(hero)
        raw = cast("dict[str, object]", invalid["ability_policy"])
        raw[field] = value
        with pytest.raises(ArtifactBundleError, match="incoherent support"):
            projection._ability_path(invalid, policy)


def test_ability_path_filters_non_integer_item_ids(tmp_path: Path) -> None:
    hero, policy, _evidence = _inputs(tmp_path)
    raw = cast("dict[str, object]", hero["ability_policy"])
    raw["selection"] = ""
    raw["filter_item_ids"] = [1, "bad", 2]
    quality = cast("dict[str, object]", raw["quality"])
    quality.update(status="pass", build_conditioned=True)

    path = projection._ability_path(hero, policy)

    assert path.selection == "MOST_SUPPORTED_LEGAL_STATE"
    assert path.filter_item_ids == (1, 2)
