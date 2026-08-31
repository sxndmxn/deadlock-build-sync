from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from deadlock_build_sync import narratives
from deadlock_build_sync.narratives import NarrativeError
from deadlock_build_sync.value_validation import object_dict, require_object_rows
from tests.test_narratives import (
    BASIS_ID,
    CONTEXT_ID,
    PATCH,
    SNAPSHOT_ID,
    guide,
    write_catalog,
)

if TYPE_CHECKING:
    from pathlib import Path


def _document(path: Path) -> dict[str, object]:
    document = object_dict(json.loads(path.read_text(encoding="utf-8")))
    assert document is not None
    return document


def test_sha_validation_rejects_wrong_type_length_and_characters(
    tmp_path: Path,
) -> None:
    assert not narratives._is_sha256(None)
    assert not narratives._is_sha256("a")
    assert not narratives._is_sha256("g" * 64)
    assert narratives._is_sha256("a" * 64)
    with pytest.raises(NarrativeError, match="fingerprint"):
        narratives._require_sha(tmp_path, "bad", "test")


def test_identity_rejects_other_snapshot_and_bad_fingerprints(tmp_path: Path) -> None:
    entry: dict[str, object] = {
        "snapshot_id": "b" * 64,
        "policy_id": "a" * 64,
        "context_sha256": "a" * 64,
        "narrative_basis_sha256": "a" * 64,
    }
    with pytest.raises(NarrativeError, match="another snapshot"):
        narratives._require_identity(tmp_path, entry, "a" * 64)

    entry["snapshot_id"] = "a" * 64
    entry["policy_id"] = "bad"
    with pytest.raises(NarrativeError, match="policy fingerprint"):
        narratives._require_identity(tmp_path, entry, "a" * 64)


def test_read_document_wraps_io_json_schema_and_generator_errors(
    tmp_path: Path,
) -> None:
    path = tmp_path / "narratives.json"
    with pytest.raises(NarrativeError, match="could not read"):
        narratives._read_narrative_document(path)
    path.write_text("{", encoding="utf-8")
    with pytest.raises(NarrativeError, match="could not read"):
        narratives._read_narrative_document(path)
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(NarrativeError, match="not a supported"):
        narratives._read_narrative_document(path)
    path.write_text(
        json.dumps({
            "schema_version": narratives.NARRATIVE_SCHEMA_VERSION,
            "generator_version": 0,
        }),
        encoding="utf-8",
    )
    with pytest.raises(NarrativeError, match="outdated"):
        narratives._read_narrative_document(path)


@pytest.mark.parametrize(
    ("overrides", "label"),
    [
        ({"patch": None}, "patch"),
        ({"cohort": None}, "cohort"),
        (
            {
                "cohort": {
                    "client_version": "123",
                    "match_mode": "ranked",
                    "game_mode": "normal",
                }
            },
            "client",
        ),
        (
            {
                "cohort": {
                    "client_version": 123,
                    "match_mode": 1,
                    "game_mode": "normal",
                }
            },
            "match mode",
        ),
        (
            {
                "cohort": {
                    "client_version": 123,
                    "match_mode": "ranked",
                    "game_mode": 1,
                }
            },
            "game mode",
        ),
        ({"requested_hero_ids": ["12"]}, "requested"),
        ({"exclusions": {}}, "exclusions"),
        ({"heroes": {}}, "heroes"),
    ],
)
def test_catalog_header_rejects_incomplete_sections(
    tmp_path: Path,
    overrides: dict[str, object],
    label: str,
) -> None:
    path = tmp_path / f"{label}.json"
    write_catalog(path)
    data = {**_document(path), **overrides}
    with pytest.raises(NarrativeError, match="missing its snapshot"):
        narratives._catalog_header(path, data)


@pytest.mark.parametrize(
    "exclusions",
    [
        [1],
        [{"hero_id": "12", "reason": "skip"}],
        [{"hero_id": 12, "reason": " "}],
    ],
)
def test_catalog_exclusions_reject_malformed_rows(
    tmp_path: Path,
    exclusions: list[object],
) -> None:
    with pytest.raises(NarrativeError, match="invalid hero exclusion"):
        narratives._catalog_exclusions(tmp_path, exclusions)


def test_catalog_exclusions_strip_reasons(tmp_path: Path) -> None:
    assert narratives._catalog_exclusions(
        tmp_path,
        [{"hero_id": 12, "reason": " skip "}],
    ) == {12: "skip"}


def test_catalog_heroes_rejects_row_identity_generator_and_duplicates(
    tmp_path: Path,
) -> None:
    path = tmp_path / "narratives.json"
    write_catalog(path)
    entry = require_object_rows(_document(path)["heroes"])[0]
    with pytest.raises(NarrativeError, match="invalid hero narrative"):
        narratives._catalog_heroes(path, [1], SNAPSHOT_ID)

    invalid = deepcopy(entry)
    invalid["path_id"] = ""
    with pytest.raises(NarrativeError, match="invalid hero narrative"):
        narratives._catalog_heroes(path, [invalid], SNAPSHOT_ID)

    outdated = deepcopy(entry)
    outdated["generator_version"] = 0
    with pytest.raises(NarrativeError, match="outdated description generator"):
        narratives._catalog_heroes(path, [outdated], SNAPSHOT_ID)

    with pytest.raises(NarrativeError, match="duplicate build"):
        narratives._catalog_heroes(path, [entry, deepcopy(entry)], SNAPSHOT_ID)


def test_catalog_coverage_rejects_overlap(tmp_path: Path) -> None:
    with pytest.raises(NarrativeError, match="both includes and excludes"):
        narratives._validate_catalog_coverage(
            tmp_path,
            {(12, "default"): {}},
            {12: "skip"},
            {12},
        )


def test_narrative_entry_checks_patch_snapshot_client_and_policy(
    tmp_path: Path,
) -> None:
    path = tmp_path / "narratives.json"
    write_catalog(path)
    catalog = narratives.load_narrative_catalog(path)
    context: dict[str, object] = {
        "context_sha256": CONTEXT_ID,
        "narrative_basis_sha256": BASIS_ID,
    }
    with pytest.raises(NarrativeError, match="patch identity"):
        narratives._narrative_entry(
            guide(),
            context,
            replace(PATCH, guid="other"),
            catalog,
        )
    with pytest.raises(NarrativeError, match="snapshot does not match"):
        narratives._narrative_entry(
            replace(guide(), snapshot_id="0" * 64),
            context,
            PATCH,
            catalog,
        )
    with pytest.raises(NarrativeError, match="client version"):
        narratives._narrative_entry(
            replace(guide(), client_version=999),
            context,
            PATCH,
            catalog,
        )
    with pytest.raises(NarrativeError, match="policy changed"):
        narratives._narrative_entry(
            replace(guide(), policy_id="0" * 64),
            context,
            PATCH,
            catalog,
        )


@pytest.mark.parametrize("reason", [None, "not ready"])
def test_narrative_entry_reports_missing_build_with_optional_reason(
    tmp_path: Path,
    reason: str | None,
) -> None:
    path = tmp_path / "narratives.json"
    write_catalog(path)
    catalog = narratives.load_narrative_catalog(path)
    exclusions = {} if reason is None else {12: reason}
    missing = replace(catalog, heroes={}, exclusions=exclusions)
    with pytest.raises(NarrativeError, match="missing Kelvin"):
        narratives._narrative_entry(guide(), {}, PATCH, missing)


def test_sentence_and_first_maxed_ability_handle_sparse_values() -> None:
    assert not narratives._sentence(None)
    assert not narratives._sentence("  ")
    assert narratives._sentence("Ready!") == "Ready!"
    assert narratives._sentence("Ready") == "Ready."
    assert not narratives._first_maxed_ability({})
    assert not narratives._first_maxed_ability({"ability_policy": {"steps": [1]}})
    assert not narratives._first_maxed_ability({
        "ability_policy": {
            "steps": [
                {"action": "UPGRADE_2", "ability": "First"},
                {"action": "UPGRADE_3", "ability": 1},
            ]
        }
    })


def test_description_supports_sparse_context_and_rejects_oversized_role() -> None:
    sparse: dict[str, object] = {
        "hero": "Kelvin",
        "policy": {"strategic_role": "Control the fight"},
    }
    description = narratives.deterministic_build_description(sparse)
    assert "Follow the shown CORE order." in description
    assert "max" not in description

    oversized: dict[str, object] = {
        "hero": "Kelvin",
        "policy": {"strategic_role": "x" * 800},
    }
    with pytest.raises(NarrativeError, match="outside its size limit"):
        narratives.deterministic_build_description(oversized)


def test_description_drops_oversized_playstyle_before_return() -> None:
    context: dict[str, object] = {
        "hero": "Kelvin",
        "hero_mechanics": {
            "description": {
                "role": "Control the fight",
                "playstyle": "x" * 800,
            }
        },
    }
    description = narratives.deterministic_build_description(context)
    assert "x" * 100 not in description
