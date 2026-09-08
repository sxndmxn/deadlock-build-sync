import copy
from dataclasses import asdict, replace
from pathlib import Path

import pytest

from deadlock_build_sync import (
    build_evidence_core,
    build_evidence_core_alternative,
    build_evidence_references,
    build_evidence_situational,
)
from deadlock_build_sync.artifacts import ArtifactError
from deadlock_build_sync.build_evidence import load_build_evidence
from deadlock_build_sync.build_evidence_types import SituationalPolicy
from deadlock_build_sync.offline.config import sha256_json
from deadlock_build_sync.value_validation import require_object_dict
from tests.build_evidence_fixtures import (
    get_first_item,
    get_situational_policy,
    make_evidence_document,
    write_evidence_document,
    write_fingerprinted_evidence,
)
from tests.build_evidence_policy_fixtures import (
    make_core_alternative,
    make_situational_branch,
)


def _parse_alternative(value: object) -> None:
    build_evidence_core_alternative.parse_core_alternative(
        value,
        13,
        {101, 102, 201, 202, 301, 302, 303, 401, 402},
        {101, 102, 201, 202, 301, 302, 401, 402},
    )


def test_core_alternative_parser_preserves_the_complete_evidence() -> None:
    result = build_evidence_core_alternative.parse_core_alternative(
        make_core_alternative(),
        13,
        {101, 102, 201, 202, 301, 302, 303, 401, 402},
        {101, 102, 201, 202, 301, 302, 401, 402},
    )

    assert sha256_json(asdict(result)) == (
        "c749d4b8615530f29d73753bcd96c67d3daa8571863990b8ef122fb9874c8adf"
    )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("item_id", 999, "invalid core alternative pair"),
        ("item_id", 302, "invalid core alternative pair"),
        ("comparator_item_id", 303, "invalid core alternative pair"),
        ("vs", "", "incomplete core alternative"),
        ("mechanics_refs", [], "lacks mechanics refs"),
        ("comparator_mechanics_refs", [7], "lacks mechanics refs"),
        ("comparative_interval", [0.01], "lacks a DR interval"),
        ("comparative_interval", [0.05, 0.01], "invalid core alternative interval"),
        ("dr_estimate", 0.08, "invalid core alternative interval"),
        ("fold_estimates", {}, "lacks temporal estimates"),
        ("fold_diagnostics", {}, "lacks fold diagnostics"),
        ("overlap", 0.4, "unqualified core alternative"),
        ("stable", False, "unqualified core alternative"),
    ],
)
def test_core_alternative_rejects_invalid_top_level_fields(
    field: str,
    value: object,
    message: str,
) -> None:
    alternative = make_core_alternative()
    alternative[field] = value

    with pytest.raises(ArtifactError, match=message):
        _parse_alternative(alternative)


def test_core_alternative_rejects_malformed_value_and_fold_diagnostics() -> None:
    with pytest.raises(ArtifactError, match="malformed core alternative"):
        _parse_alternative([])

    missing_interval = make_core_alternative()
    diagnostics = require_object_dict(missing_interval["fold_diagnostics"])
    train = require_object_dict(diagnostics["train"])
    train["interval"] = []
    with pytest.raises(ArtifactError, match="lacks a train interval"):
        _parse_alternative(missing_interval)

    unqualified = make_core_alternative()
    diagnostics = require_object_dict(unqualified["fold_diagnostics"])
    train = require_object_dict(diagnostics["train"])
    train["overlap"] = 0.4
    with pytest.raises(ArtifactError, match="unqualified train"):
        _parse_alternative(unqualified)


def test_core_alternative_rejects_temporal_instability() -> None:
    alternative = make_core_alternative()
    estimates = require_object_dict(alternative["fold_estimates"])
    diagnostics = require_object_dict(alternative["fold_diagnostics"])
    estimates["validation"] = 0.09
    validation = require_object_dict(diagnostics["validation"])
    validation["estimate"] = 0.09
    validation["interval"] = [0.08, 0.10]

    with pytest.raises(ArtifactError, match="unstable core alternative"):
        _parse_alternative(alternative)


def test_core_parser_rejects_duplicate_items_denominators_and_alternatives() -> None:
    row = get_first_item(make_evidence_document())
    with pytest.raises(ArtifactError, match="duplicate item evidence"):
        build_evidence_core._parse_hero_items([row, row], 13, 1_000)
    with pytest.raises(ArtifactError, match="item denominators disagree"):
        build_evidence_core._parse_hero_items([row], 13, 999)

    alternative = make_core_alternative()
    with pytest.raises(ArtifactError, match="invalid core alternatives"):
        build_evidence_core._parse_core_alternatives(
            [alternative, copy.deepcopy(alternative)],
            13,
            {101, 102, 201, 202, 301, 302, 303, 401, 402},
            (101, 102, 201, 202, 301, 302, 401, 402),
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("threat", "bad", "incomplete situational branch"),
        ("enemy_scope", "nearby", "incomplete situational branch"),
        ("trigger", "", "incomplete situational branch"),
        ("enemy_mechanics_refs", [], "lacks enemy mechanics refs"),
        ("enemy_mechanics_refs", [7], "lacks enemy mechanics refs"),
        ("enemy_hero_id", 0, "enemy hero id"),
        ("comparator_item_id", 103, "compares a situational item with itself"),
        ("mechanic_ref", "item/999/healing", "mismatched situational mechanic"),
        ("comparative_interval", [0.01], "no bounded situational"),
        ("comparative_interval", [0.06, 0.01], "unqualified situational"),
        ("comparative_interval", [0.0, 0.01], "unqualified situational"),
        ("comparative_interval", [0.01, 0.12], "unqualified situational"),
        ("fold_comparative_estimates", {}, "lacks situational fold evidence"),
        ("fold_support", {}, "lacks situational fold evidence"),
    ],
)
def test_situational_branch_rejects_invalid_fields(
    field: str,
    value: object,
    message: str,
) -> None:
    branch = make_situational_branch()
    branch[field] = value

    with pytest.raises(ArtifactError, match=message):
        build_evidence_situational.parse_situational_branch(branch, 13)


def test_situational_branch_accepts_team_scope_without_one_enemy() -> None:
    branch = make_situational_branch()
    branch["enemy_hero_id"] = None

    parsed = build_evidence_situational.parse_situational_branch(branch, 13)

    assert parsed.enemy_hero_id is None


def test_situational_branch_rejects_malformed_fold_support() -> None:
    branch = make_situational_branch()
    support = require_object_dict(branch["fold_support"])
    support["train"] = []

    with pytest.raises(ArtifactError, match="lacks situational train support"):
        build_evidence_situational.parse_situational_branch(branch, 13)


def test_situational_policy_rejects_duplicate_identity_and_repeated_item(
    tmp_path: Path,
) -> None:
    path = tmp_path / "build-evidence.json"
    duplicate = make_evidence_document()
    get_situational_policy(duplicate)["branches"] = [
        make_situational_branch(),
        make_situational_branch(),
    ]
    write_fingerprinted_evidence(path, duplicate)
    with pytest.raises(ArtifactError, match="duplicate situational branches"):
        load_build_evidence(path)

    repeated = make_evidence_document()
    second = make_situational_branch()
    second["threat"] = "control"
    get_situational_policy(repeated)["branches"] = [make_situational_branch(), second]
    write_fingerprinted_evidence(path, repeated)
    with pytest.raises(ArtifactError, match="repeats a situational item"):
        load_build_evidence(path)


def test_policy_references_reject_missing_weak_and_mismatched_items(
    tmp_path: Path,
) -> None:
    path = tmp_path / "build-evidence.json"
    write_evidence_document(path, make_evidence_document())
    hero = load_build_evidence(path).heroes[13]
    sequence_policy = hero.sequence_policy
    assert sequence_policy is not None
    branch = build_evidence_situational.parse_situational_branch(
        make_situational_branch(), 13
    )
    situational = SituationalPolicy((branch,), ())

    missing_sequence = replace(
        sequence_policy,
        default_path=(*sequence_policy.default_path, 999),
    )
    with pytest.raises(ArtifactError, match="references missing item"):
        build_evidence_references.validate_policy_item_references(
            hero.core_policy,
            hero.tier_policy,
            missing_sequence,
            situational,
            items=hero.items,
            hero_id=13,
        )

    weak_items = tuple(
        replace(item, adopter_matches=19) if item.item_id == branch.item_id else item
        for item in hero.items
    )
    with pytest.raises(ArtifactError, match="weak situational tier item"):
        build_evidence_references.validate_policy_item_references(
            hero.core_policy,
            hero.tier_policy,
            sequence_policy,
            situational,
            items=weak_items,
            hero_id=13,
        )

    mismatched = SituationalPolicy((replace(branch, comparator_item_id=201),), ())
    with pytest.raises(ArtifactError, match="invalid situational comparator"):
        build_evidence_references.validate_policy_item_references(
            hero.core_policy,
            hero.tier_policy,
            sequence_policy,
            mismatched,
            items=hero.items,
            hero_id=13,
        )
