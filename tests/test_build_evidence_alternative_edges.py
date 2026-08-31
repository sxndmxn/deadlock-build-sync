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
    _document,
    _first_item,
    _refingerprint,
    _situational_policy,
    _write,
)


def _alternative() -> dict[str, object]:
    return {
        "item_id": 303,
        "comparator_item_id": 302,
        "stage": 6,
        "support": 40,
        "comparison_support": 50,
        "effective_support": 30.0,
        "overlap": 0.8,
        "stable": True,
        "dr_estimate": 0.03,
        "comparative_interval": [0.01, 0.05],
        "vs": "Heavy Spirit damage",
        "why": "Spirit Resist",
        "swap": "Replaces Tier 3 Item 2",
        "when": "Before the next Spirit-heavy fight",
        "skip": "Keep default when control matters more",
        "mechanics_refs": ["asset:item:303:description"],
        "comparator_mechanics_refs": ["asset:item:302:description"],
        "fold_estimates": {
            "train": 0.03,
            "validation": 0.04,
            "test": -0.03,
        },
        "fold_diagnostics": {
            fold: {
                "support": 40,
                "comparison_support": 50,
                "effective_support": 30.0,
                "overlap": 0.8,
                "maximum_standardized_mean_difference": 0.05,
                "estimate": estimate,
                "interval": [0.01, 0.05],
            }
            for fold, estimate in (("train", 0.03), ("validation", 0.04))
        },
    }


def _branch() -> dict[str, object]:
    return {
        "threat": "healing",
        "item_id": 103,
        "enemy_hero_id": 7,
        "enemy_scope": "whole_enemy_team",
        "phase": 1,
        "tier": 1,
        "mechanic_ref": "item/103/healing-reduction",
        "enemy_mechanics_refs": ["asset:ability:7:description"],
        "comparator": "same-tier default continuation or save",
        "comparator_item_id": 101,
        "comparison_support": 20,
        "same_opportunity": True,
        "support": 20,
        "effective_support": 20.0,
        "overlap": 0.5,
        "stable": True,
        "comparative_interval": [0.01, 0.06],
        "fold_comparative_estimates": {
            "train": 0.03,
            "validation": 0.04,
            "test": 0.02,
        },
        "fold_support": {
            "train": {"item": 20, "comparator": 20},
            "validation": {"item": 20, "comparator": 20},
            "test": {"item": 20, "comparator": 20},
        },
        "trigger": "Enemy healing is observed.",
        "replacement": "Replace the next optional purchase.",
        "execution": "Apply healing reduction after contact.",
        "failure_condition": "Skip when healing is not material.",
    }


def _parse_alternative(value: object) -> None:
    build_evidence_core_alternative.parse_core_alternative(
        value,
        13,
        {101, 102, 201, 202, 301, 302, 303, 401, 402},
        {101, 102, 201, 202, 301, 302, 401, 402},
    )


def test_core_alternative_parser_preserves_the_complete_evidence() -> None:
    result = build_evidence_core_alternative.parse_core_alternative(
        _alternative(),
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
    alternative = _alternative()
    alternative[field] = value

    with pytest.raises(ArtifactError, match=message):
        _parse_alternative(alternative)


def test_core_alternative_rejects_malformed_value_and_fold_diagnostics() -> None:
    with pytest.raises(ArtifactError, match="malformed core alternative"):
        _parse_alternative([])

    missing_interval = _alternative()
    diagnostics = require_object_dict(missing_interval["fold_diagnostics"])
    train = require_object_dict(diagnostics["train"])
    train["interval"] = []
    with pytest.raises(ArtifactError, match="lacks a train interval"):
        _parse_alternative(missing_interval)

    unqualified = _alternative()
    diagnostics = require_object_dict(unqualified["fold_diagnostics"])
    train = require_object_dict(diagnostics["train"])
    train["overlap"] = 0.4
    with pytest.raises(ArtifactError, match="unqualified train"):
        _parse_alternative(unqualified)


def test_core_alternative_rejects_temporal_instability() -> None:
    alternative = _alternative()
    estimates = require_object_dict(alternative["fold_estimates"])
    diagnostics = require_object_dict(alternative["fold_diagnostics"])
    estimates["validation"] = 0.09
    validation = require_object_dict(diagnostics["validation"])
    validation["estimate"] = 0.09
    validation["interval"] = [0.08, 0.10]

    with pytest.raises(ArtifactError, match="unstable core alternative"):
        _parse_alternative(alternative)


def test_core_parser_rejects_duplicate_items_denominators_and_alternatives() -> None:
    row = _first_item(_document())
    with pytest.raises(ArtifactError, match="duplicate item evidence"):
        build_evidence_core._hero_items([row, row], 13, 1_000)
    with pytest.raises(ArtifactError, match="item denominators disagree"):
        build_evidence_core._hero_items([row], 13, 999)

    alternative = _alternative()
    with pytest.raises(ArtifactError, match="invalid core alternatives"):
        build_evidence_core._core_alternatives(
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
    branch = _branch()
    branch[field] = value

    with pytest.raises(ArtifactError, match=message):
        build_evidence_situational.parse_situational_branch(branch, 13)


def test_situational_branch_accepts_team_scope_without_one_enemy() -> None:
    branch = _branch()
    branch["enemy_hero_id"] = None

    parsed = build_evidence_situational.parse_situational_branch(branch, 13)

    assert parsed.enemy_hero_id is None


def test_situational_branch_rejects_malformed_fold_support() -> None:
    branch = _branch()
    support = require_object_dict(branch["fold_support"])
    support["train"] = []

    with pytest.raises(ArtifactError, match="lacks situational train support"):
        build_evidence_situational.parse_situational_branch(branch, 13)


def test_situational_policy_rejects_duplicate_identity_and_repeated_item(
    tmp_path: Path,
) -> None:
    path = tmp_path / "build-evidence.json"
    duplicate = _document()
    _situational_policy(duplicate)["branches"] = [_branch(), _branch()]
    _refingerprint(duplicate)
    _write(path, duplicate)
    with pytest.raises(ArtifactError, match="duplicate situational branches"):
        load_build_evidence(path)

    repeated = _document()
    second = _branch()
    second["threat"] = "control"
    _situational_policy(repeated)["branches"] = [_branch(), second]
    _refingerprint(repeated)
    _write(path, repeated)
    with pytest.raises(ArtifactError, match="repeats a situational item"):
        load_build_evidence(path)


def test_policy_references_reject_missing_weak_and_mismatched_items(
    tmp_path: Path,
) -> None:
    path = tmp_path / "build-evidence.json"
    _write(path, _document())
    hero = load_build_evidence(path).heroes[13]
    sequence_policy = hero.sequence_policy
    assert sequence_policy is not None
    branch = build_evidence_situational.parse_situational_branch(_branch(), 13)
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
