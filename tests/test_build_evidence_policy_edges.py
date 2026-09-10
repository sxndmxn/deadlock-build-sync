from dataclasses import replace
from pathlib import Path

import pytest

from deadlock_build_sync import build_evidence_core
from deadlock_build_sync.artifacts import ArtifactError
from deadlock_build_sync.build_evidence import load_build_evidence
from deadlock_build_sync.value_validation import (
    require_object_dict,
    require_object_list,
)
from tests.build_evidence_fixtures import (
    get_first_build,
    get_sequence_policy,
    get_situational_policy,
    make_evidence_document,
    write_evidence_document,
    write_fingerprinted_evidence,
)


def _core_policy(document: dict[str, object]) -> dict[str, object]:
    return require_object_dict(get_first_build(document)["core_policy"])


def _tier_policy(document: dict[str, object]) -> dict[str, object]:
    return require_object_dict(get_first_build(document)["tier_policy"])


def _expect_load_error(
    path: Path,
    document: dict[str, object],
    message: str,
) -> None:
    write_fingerprinted_evidence(path, document)
    with pytest.raises(ArtifactError, match=message):
        load_build_evidence(path)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("backbone_item_ids", None),
        ("default_item_ids", None),
        ("alternatives", None),
        ("candidate_audit", None),
        ("backbone_fold_matches", None),
        ("default_fold_matches", None),
        ("evaluation", None),
    ],
)
def test_core_policy_requires_all_structured_fields(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    document = make_evidence_document()
    _core_policy(document)[field] = value

    _expect_load_error(
        tmp_path / "build-evidence.json",
        document,
        "incomplete core policy",
    )


def test_core_policy_rejects_an_unsupported_version(tmp_path: Path) -> None:
    document = make_evidence_document()
    _core_policy(document)["version"] = 2

    _expect_load_error(
        tmp_path / "build-evidence.json", document, "no supported core policy"
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("backbone_item_ids", [101, 102]),
        ("backbone_item_ids", [101, 101, 201, 202]),
        ("default_item_ids", [101, 102, 201]),
        ("default_item_ids", [101, 102, 201, 202, 202]),
        ("default_item_ids", [101, 102, 201, 202, 999]),
    ],
)
def test_core_policy_rejects_invalid_membership(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    document = make_evidence_document()
    _core_policy(document)[field] = value

    _expect_load_error(
        tmp_path / "build-evidence.json",
        document,
        "invalid core policy membership",
    )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("backbone_matches", 61, "backbone support exceeds"),
        ("default_matches", 79, "default support exceeds"),
        ("default_matches", 1_001, "default support exceeds"),
    ],
)
def test_core_policy_rejects_inconsistent_support(
    tmp_path: Path,
    field: str,
    value: object,
    message: str,
) -> None:
    document = make_evidence_document()
    _core_policy(document)[field] = value

    _expect_load_error(tmp_path / "build-evidence.json", document, message)


def test_core_policy_rejects_malformed_candidate_audit(tmp_path: Path) -> None:
    document = make_evidence_document()
    _core_policy(document)["candidate_audit"] = [7]

    _expect_load_error(
        tmp_path / "build-evidence.json",
        document,
        "malformed core candidate audit",
    )


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (("version", 0), "no supported tier policy"),
        (("item_ids_by_tier", None), "incomplete tier policy"),
    ],
)
def test_tier_policy_rejects_unsupported_structure(
    tmp_path: Path,
    change: tuple[str, object],
    message: str,
) -> None:
    document = make_evidence_document()
    field, value = change
    _tier_policy(document)[field] = value

    _expect_load_error(tmp_path / "build-evidence.json", document, message)


def test_tier_policy_rejects_missing_malformed_and_duplicate_membership(
    tmp_path: Path,
) -> None:
    path = tmp_path / "build-evidence.json"

    missing = make_evidence_document()
    membership = require_object_dict(_tier_policy(missing)["item_ids_by_tier"])
    membership.pop("4")
    _expect_load_error(path, missing, "incomplete tier policy")

    malformed = make_evidence_document()
    membership = require_object_dict(_tier_policy(malformed)["item_ids_by_tier"])
    membership["1"] = "bad"
    _expect_load_error(path, malformed, "malformed Tier 1 policy")

    empty = make_evidence_document()
    membership = require_object_dict(_tier_policy(empty)["item_ids_by_tier"])
    membership["1"] = []
    _expect_load_error(path, empty, "Item pool differs")

    duplicate = make_evidence_document()
    membership = require_object_dict(_tier_policy(duplicate)["item_ids_by_tier"])
    tier_one = require_object_list(membership["1"])
    tier_one[1] = tier_one[0]
    _expect_load_error(path, duplicate, "invalid Tier 1 membership")

    wrong_tier = make_evidence_document()
    membership = require_object_dict(_tier_policy(wrong_tier)["item_ids_by_tier"])
    require_object_list(membership["1"])[0] = 203
    _expect_load_error(path, wrong_tier, "unsupported Tier 1 item")

    repeated = make_evidence_document()
    membership = require_object_dict(_tier_policy(repeated)["item_ids_by_tier"])
    tier_one_id = require_object_list(membership["1"])[0]
    require_object_list(membership["2"])[0] = tier_one_id
    _expect_load_error(path, repeated, "unsupported Tier 2 item")


def test_discovery_pool_requires_discovery_buyers_and_ignores_validation_shortlists(
    tmp_path: Path,
) -> None:
    path = tmp_path / "build-evidence.json"
    write_evidence_document(path, make_evidence_document())
    hero = load_build_evidence(path).heroes[13]
    policy_value = get_first_build(make_evidence_document())["tier_policy"]
    first_id = hero.tier_policy.item_ids_by_tier[1][0]
    target = next(item for item in hero.items if item.item_id == first_id)

    for changed in (
        replace(target, validation_adopter_matches=19),
        replace(target, training_adoption=0.04),
        replace(target, validation_adoption=0.04),
        replace(target, training_adoption=0.30, validation_adoption=0.05),
    ):
        items = tuple(
            changed if item.item_id == first_id else item for item in hero.items
        )
        assert (
            first_id
            in build_evidence_core._parse_tier_policy(
                policy_value, 13, items
            ).item_ids_by_tier[1]
        )
    items = tuple(
        replace(item, training_adopter_matches=19) if item.item_id == first_id else item
        for item in hero.items
    )
    with pytest.raises(ArtifactError, match="unsupported Tier 1 item"):
        build_evidence_core._parse_tier_policy(policy_value, 13, items)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("component_expanded_default_path", None),
        ("component_expanded_default_path", []),
        ("transitions", None),
        ("transitions", []),
        ("evaluation", None),
        ("production_model", "other"),
    ],
)
def test_sequence_policy_requires_complete_inputs(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    document = make_evidence_document()
    get_sequence_policy(document)[field] = value

    _expect_load_error(
        tmp_path / "build-evidence.json",
        document,
        "incomplete sequence policy",
    )


def test_sequence_policy_rejects_bad_transitions(tmp_path: Path) -> None:
    path = tmp_path / "build-evidence.json"

    malformed = make_evidence_document()
    get_sequence_policy(malformed)["transitions"] = [7]
    _expect_load_error(path, malformed, "malformed sequence transition")

    bad_level = make_evidence_document()
    transitions = require_object_list(get_sequence_policy(bad_level)["transitions"])
    require_object_dict(transitions[0])["level"] = "bad"
    _expect_load_error(path, bad_level, "invalid sequence backoff level")

    bad_context = make_evidence_document()
    transitions = require_object_list(get_sequence_policy(bad_context)["transitions"])
    require_object_dict(transitions[0])["context_support"] = 49
    _expect_load_error(path, bad_context, "transition context support")

    weak = make_evidence_document()
    transitions = require_object_list(get_sequence_policy(weak)["transitions"])
    require_object_dict(transitions[0])["support"] = 19
    _expect_load_error(path, weak, "weak sequence transition")


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("version", 1, "no supported situational policy"),
        ("branches", None, "incomplete situational policy"),
        ("abstentions", None, "incomplete situational policy"),
        ("threat_vocabulary", [], "incomplete situational policy"),
        ("branches", [None] * 8, "too many situational branches"),
        ("abstentions", [""], "invalid situational abstention"),
    ],
)
def test_situational_policy_rejects_invalid_structure(
    tmp_path: Path,
    field: str,
    value: object,
    message: str,
) -> None:
    document = make_evidence_document()
    get_situational_policy(document)[field] = value

    _expect_load_error(tmp_path / "build-evidence.json", document, message)


def test_situational_policy_requires_a_branch_or_abstention(tmp_path: Path) -> None:
    document = make_evidence_document()
    get_situational_policy(document)["abstentions"] = []

    _expect_load_error(
        tmp_path / "build-evidence.json", document, "no situational result"
    )
