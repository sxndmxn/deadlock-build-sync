from __future__ import annotations

import json
from copy import deepcopy
from typing import TYPE_CHECKING

import pytest

from deadlock_build_sync import strategy_context_validation as validation
from deadlock_build_sync.value_validation import object_dict, require_object_rows
from tests.artifact_bundle_fixtures import write_artifact_bundle

if TYPE_CHECKING:
    from pathlib import Path


def _document(tmp_path: Path) -> dict[str, object]:
    context_path, _policy_path, _narrative_path, _evidence_path = write_artifact_bundle(
        tmp_path
    )
    document = object_dict(json.loads(context_path.read_text(encoding="utf-8")))
    assert document is not None
    return document


def _hero(document: dict[str, object]) -> dict[str, object]:
    return require_object_rows(document["heroes"])[0]


def _manifest(document: dict[str, object]) -> dict[str, object]:
    manifest = object_dict(document["snapshot_manifest"])
    assert manifest is not None
    return manifest


def test_build_identity_requires_projection_and_valid_tags(tmp_path: Path) -> None:
    document = _document(tmp_path)
    hero = _hero(document)
    manifest = _manifest(document)
    with pytest.raises(validation.StrategyContextError, match="no build identity"):
        validation._validate_build_identity({}, manifest)

    invalid = deepcopy(hero)
    projection = object_dict(invalid["projection"])
    assert projection is not None
    build = object_dict(projection["build"])
    assert build is not None
    build["tag_ids"] = [1, 1, 2]
    with pytest.raises(validation.StrategyContextError, match="invalid build tags"):
        validation._validate_build_identity(invalid, manifest)

    build["tag_ids"] = [1, 2, 3]
    build["tag_classes"] = ["one", "two", "invalid"]
    with pytest.raises(validation.StrategyContextError, match="invalid build tags"):
        validation._validate_build_identity(invalid, manifest)


def test_item_mechanics_catalog_handles_known_and_missing_assets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        validation,
        "extract_asset_mechanics",
        lambda asset: {"name": asset.get("name")},
    )
    catalog = validation.build_item_mechanics_catalog(
        [{"id": 1, "name": "Known"}, {"id": "2"}],
        {1, 2},
    )
    assert catalog == {"1": {"name": "Known"}, "2": {}}


def test_context_item_records_reads_core_optional_and_tiers() -> None:
    entry: dict[str, object] = {
        "core": {
            "items": [{"item_id": 1}],
            "optional_core_substitution_cards": [{"item_id": 2}],
        },
        "tiers": {"1": [{"item_id": 3}], "2": "bad"},
    }
    assert [
        row["item_id"] for row in validation._collect_context_item_records(entry)
    ] == [
        1,
        2,
        3,
    ]
    assert validation._collect_context_item_records({}) == []


@pytest.mark.parametrize(
    "value",
    [None, {"bad": {}}, {"0": {}}, {"01": {}}, {"1": []}],
)
def test_item_mechanics_document_rejects_invalid_keys_and_rows(value: object) -> None:
    with pytest.raises(validation.StrategyContextError, match="invalid item mechanics"):
        validation._parse_item_mechanics_records(value)


@pytest.mark.parametrize(
    "item_ids",
    [None, [1, "2"], [0], [2, 1], [1, 1]],
)
def test_hero_item_mechanics_rejects_invalid_reference_lists(
    item_ids: object,
) -> None:
    entry: dict[str, object] = {"item_mechanics_ids": item_ids}
    with pytest.raises(validation.StrategyContextError, match="invalid item mechanics"):
        validation._validate_hero_item_mechanics(entry, {}, "Hero")


def test_hero_item_mechanics_rejects_record_mismatch_and_inline_mechanics() -> None:
    mismatch: dict[str, object] = {
        "item_mechanics_ids": [],
        "core": {"items": [{"item_id": 1}]},
    }
    with pytest.raises(validation.StrategyContextError, match="references differ"):
        validation._validate_hero_item_mechanics(mismatch, {}, "Hero")

    inline: dict[str, object] = {
        "item_mechanics_ids": [1],
        "core": {"items": [{"item_id": 1, "mechanics": {}}]},
    }
    with pytest.raises(validation.StrategyContextError, match="references differ"):
        validation._validate_hero_item_mechanics(inline, {"1": {}}, "Hero")


def test_hero_item_mechanics_rejects_missing_and_edited_catalog() -> None:
    entry: dict[str, object] = {
        "item_mechanics_ids": [1],
        "core": {"items": [{"item_id": 1}]},
        "item_mechanics_sha256": "wrong",
    }
    with pytest.raises(validation.StrategyContextError, match="missing item mechanics"):
        validation._validate_hero_item_mechanics(entry, {}, "Hero")
    with pytest.raises(validation.StrategyContextError, match="were edited"):
        validation._validate_hero_item_mechanics(entry, {"1": {}}, "Hero")


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"snapshot_manifest": None}, "snapshot manifest"),
        ({"heroes": None}, "heroes array"),
        ({"requested_hero_ids": ["12"]}, "requested heroes"),
        ({"exclusions": None}, "invalid exclusions"),
        (
            {"exclusions": [{"hero_id": 13, "reason": " "}]},
            "invalid exclusions",
        ),
    ],
)
def test_strategy_context_header_rejects_invalid_sections(
    tmp_path: Path,
    change: dict[str, object],
    message: str,
) -> None:
    document = {**_document(tmp_path), **change}
    with pytest.raises(validation.StrategyContextError, match=message):
        validation._parse_strategy_context_header(document)


@pytest.mark.parametrize(
    "entry",
    [None, {}, {"hero_id": "12", "path_id": "default"}, {"hero_id": 12, "path_id": ""}],
)
def test_context_build_key_rejects_invalid_identity(entry: object) -> None:
    with pytest.raises(validation.StrategyContextError, match="invalid hero"):
        validation._parse_context_build_key(entry)


def test_validate_context_hero_checks_snapshot_and_all_fingerprints(
    tmp_path: Path,
) -> None:
    document = _document(tmp_path)
    hero = _hero(document)
    manifest = _manifest(document)
    mechanics = validation._parse_item_mechanics_records(document["item_mechanics"])

    changed = deepcopy(hero)
    changed["snapshot_id"] = "wrong"
    with pytest.raises(validation.StrategyContextError, match="snapshot differs"):
        validation._validate_context_hero(changed, manifest, mechanics)

    changed = deepcopy(hero)
    changed["narrative_basis_sha256"] = "wrong"
    with pytest.raises(validation.StrategyContextError, match="tactical basis"):
        validation._validate_context_hero(changed, manifest, mechanics)

    changed = deepcopy(hero)
    changed["context_sha256"] = "wrong"
    with pytest.raises(validation.StrategyContextError, match="context was edited"):
        validation._validate_context_hero(changed, manifest, mechanics)


def test_context_coverage_rejects_overlap_and_unreferenced_mechanics() -> None:
    with pytest.raises(validation.StrategyContextError, match="both includes"):
        validation._validate_context_coverage(
            {12},
            set(),
            [12],
            [{"hero_id": 12, "reason": "skip"}],
            {},
        )
    with pytest.raises(validation.StrategyContextError, match="unreferenced"):
        validation._validate_context_coverage(
            {12},
            set(),
            [12],
            [],
            {"1": {}},
        )


def test_document_validation_rejects_schema_duplicate_build_and_source_hash(
    tmp_path: Path,
) -> None:
    document = _document(tmp_path)
    invalid_schema = {**document, "schema_version": 0}
    with pytest.raises(validation.StrategyContextError, match="unsupported"):
        validation.validate_strategy_context_document(invalid_schema)

    duplicated = deepcopy(document)
    duplicated["heroes"] = [deepcopy(_hero(document)), deepcopy(_hero(document))]
    with pytest.raises(validation.StrategyContextError, match="duplicate build"):
        validation.validate_strategy_context_document(duplicated)

    edited = deepcopy(document)
    edited["source_context_sha256"] = "wrong"
    with pytest.raises(validation.StrategyContextError, match="document was edited"):
        validation.validate_strategy_context_document(edited)
