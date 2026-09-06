from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
from typing import TYPE_CHECKING, cast

import pytest

from deadlock_build_sync import artifact_projection as projection
from deadlock_build_sync.artifact_bundle_types import ArtifactBundleError
from deadlock_build_sync.build_evidence import HeroBuildEvidence, load_build_evidence
from deadlock_build_sync.policy import Branch, BuildPolicy, NodeKind, PolicyNode
from deadlock_build_sync.purchase_guide import GuideItem, guide_item_from_evidence
from deadlock_build_sync.value_validation import object_dict, require_object_rows
from tests.artifact_bundle_fixtures import _policy, _projection, _write_bundle

if TYPE_CHECKING:
    from pathlib import Path


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


def _categories(hero: dict[str, object]) -> list[dict[str, object]]:
    projected = object_dict(hero["projection"])
    assert projected is not None
    return require_object_rows(projected["categories"])


def _items(hero: dict[str, object], row: int) -> list[dict[str, object]]:
    return require_object_rows(_categories(hero)[row]["items"])


def _guide_items(evidence: HeroBuildEvidence, count: int = 6) -> tuple[GuideItem, ...]:
    return tuple(guide_item_from_evidence(item) for item in evidence.items[:count])


def test_policy_core_rejects_dangling_choice_and_non_purchase_nodes() -> None:
    policy = _policy("snapshot")
    dangling = deepcopy(policy)
    vars(dangling)["entry"] = "missing"
    with pytest.raises(ArtifactBundleError, match="dangling"):
        projection._policy_core(dangling)

    choice = PolicyNode(
        "choice",
        NodeKind.CHOICE,
        branches=(Branch("core-1"), Branch("core-2")),
    )
    with pytest.raises(ArtifactBundleError, match="no unique default"):
        projection._policy_core(replace(policy, entry="choice", nodes=(choice,)))

    ability = PolicyNode("ability", NodeKind.ABILITY, ability_id=10, level=1)
    with pytest.raises(ArtifactBundleError, match="not a purchase-only path"):
        projection._policy_core(replace(policy, entry="ability", nodes=(ability,)))


def test_policy_core_rejects_open_end_cycle_and_short_path() -> None:
    policy = _policy("snapshot")
    open_end = PolicyNode("open", NodeKind.PURCHASE, item_id=1)
    with pytest.raises(ArtifactBundleError, match="ends without an end node"):
        projection._policy_core(replace(policy, entry="open", nodes=(open_end,)))

    cycle = (
        PolicyNode("one", NodeKind.PURCHASE, next_id="two", item_id=1),
        PolicyNode("two", NodeKind.PURCHASE, next_id="one", item_id=2),
    )
    with pytest.raises(ArtifactBundleError, match="contains a cycle"):
        projection._policy_core(replace(policy, entry="one", nodes=cycle))

    short = (
        PolicyNode("one", NodeKind.PURCHASE, next_id="end", item_id=1),
        PolicyNode("end", NodeKind.END),
    )
    with pytest.raises(ArtifactBundleError, match="unsupported item count"):
        projection._policy_core(replace(policy, entry="one", nodes=short))


@pytest.mark.parametrize("value", [-1, True, "1"])
def test_optional_int_rejects_invalid_values(value: object) -> None:
    assert projection._optional_int(None, "field") is None
    with pytest.raises(ArtifactBundleError, match="invalid field"):
        projection._optional_int(value, "field")


def test_projected_annotation_rejects_missing_and_stale_text(tmp_path: Path) -> None:
    _hero, _policy_value, evidence = _inputs(tmp_path)
    item = guide_item_from_evidence(evidence.items[0])
    with pytest.raises(ArtifactBundleError, match="no item annotation"):
        projection._check_projected_annotation(item, None)
    with pytest.raises(ArtifactBundleError, match="stale annotation"):
        projection._check_projected_annotation(item, "USE: old copy")

    assert projection._check_projected_annotation(item, item.annotation) is None


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ([], "malformed item"),
        ({"item_id": 0, "item": "Item"}, "incomplete item"),
        ({"item_id": 1001, "item": ""}, "incomplete item"),
        (
            {"item_id": 9999, "item": "Other", "annotation": "SOUL WINDOW: 1k - 2k"},
            "conflicts with build evidence",
        ),
    ],
)
def test_guide_item_rejects_malformed_values(
    tmp_path: Path,
    value: object,
    message: str,
) -> None:
    _hero, _policy_value, evidence = _inputs(tmp_path)
    with pytest.raises(ArtifactBundleError, match=message):
        projection._guide_item(value, evidence=evidence, expected_tier=None)


def test_guide_item_rejects_wrong_tier_and_invalid_optional_number(
    tmp_path: Path,
) -> None:
    hero, _policy_value, evidence = _inputs(tmp_path)
    core_item = deepcopy(_items(hero, 0)[0])
    with pytest.raises(ArtifactBundleError, match="wrong tier"):
        projection._guide_item(core_item, evidence=evidence, expected_tier=4)

    core_item["required_flex_slots"] = True
    with pytest.raises(ArtifactBundleError, match="flex-slot requirement"):
        projection._guide_item(core_item, evidence=evidence, expected_tier=None)


def test_projection_rows_and_category_shape_are_strict(tmp_path: Path) -> None:
    hero, _policy_value, evidence = _inputs(tmp_path)
    with pytest.raises(ArtifactBundleError, match="wrong row count"):
        projection._projection_category_rows({}, (), evidence.hero_id)

    spec: projection._CategorySpec = ("CORE ITEMS", False, 6, 6, None)
    with pytest.raises(ArtifactBundleError, match="is malformed"):
        projection._projected_category([], spec, evidence=evidence)

    malformed = deepcopy(_categories(hero)[0])
    malformed["optional"] = True
    with pytest.raises(ArtifactBundleError, match="is malformed"):
        projection._projected_category(malformed, spec, evidence=evidence)


def test_projected_category_rejects_duplicates_and_dimensions(tmp_path: Path) -> None:
    hero, _policy_value, evidence = _inputs(tmp_path)
    tier = deepcopy(_categories(hero)[1])
    tier_items = require_object_rows(tier["items"])
    tier_items[1] = deepcopy(tier_items[0])
    tier["items"] = tier_items
    spec: projection._CategorySpec = ("TIER 1", True, 1, 10, 1)
    with pytest.raises(ArtifactBundleError, match="contains duplicates"):
        projection._projected_category(tier, spec, evidence=evidence)

    core = deepcopy(_categories(hero)[0])
    core["width"] = True
    with pytest.raises(ArtifactBundleError, match="invalid dimensions"):
        projection._projected_category(
            core,
            ("CORE ITEMS", False, 6, 6, None),
            evidence=evidence,
        )


def test_final_core_and_projected_sets_reject_mismatches(tmp_path: Path) -> None:
    _hero, _policy_value, evidence = _inputs(tmp_path)
    items = _guide_items(evidence)
    item_ids = tuple(item.item_id for item in items)
    with pytest.raises(ArtifactBundleError, match="component-expanded evidence"):
        projection._final_core_items(items, tuple(reversed(item_ids)), item_ids, 12)
    with pytest.raises(ArtifactBundleError, match="omits final items"):
        projection._final_core_items(items, item_ids, (*item_ids, 9999), 12)
    with pytest.raises(ArtifactBundleError, match="differs from its policy"):
        projection._validate_projected_item_sets(
            items,
            (),
            {},
            tuple(reversed(item_ids)),
            12,
        )
    with pytest.raises(ArtifactBundleError, match="repeat items"):
        projection._validate_projected_item_sets(items, (items[0],), {}, item_ids, 12)


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
