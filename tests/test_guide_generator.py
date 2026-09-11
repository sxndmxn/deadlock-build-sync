"""Reject incompatible generators and malformed beam evidence."""

from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING

import pytest

from deadlock_build_sync.artifacts import ArtifactError
from deadlock_build_sync.build_evidence import METHOD_VERSION, load_build_evidence
from deadlock_build_sync.cli_parser import build_parser
from deadlock_build_sync.guide_generator import (
    generator_record,
    require_generator,
    validate_generator_header,
    validate_generator_path,
    validate_state_row,
)
from deadlock_build_sync.offline.beam_export import (
    assemble_group,
    attach_group_metadata,
)
from deadlock_build_sync.purchase_windows import wilson_score_interval
from deadlock_build_sync.value_validation import (
    require_object_dict,
    require_object_rows,
)
from tests.beam_fixtures import (
    make_beam_document,
    make_generator_path,
    make_state_evidence,
)
from tests.build_evidence_fixtures import (
    make_evidence_document,
    write_fingerprinted_evidence,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("command", ["build", "sync", "refresh-evidence"])
def test_generator_selection_is_optional(command: str) -> None:
    parser = build_parser()
    assert parser.parse_args([command]).generator == "current"
    assert parser.parse_args([command, "--generator", "beam"]).generator == "beam"


@pytest.mark.parametrize("effective", ["beam", "current"])
def test_loads_versioned_beam_and_explicit_fallback(
    tmp_path: Path, effective: str
) -> None:
    path = tmp_path / "evidence.json"
    write_fingerprinted_evidence(path, make_beam_document(effective=effective))
    catalog = load_build_evidence(path)
    assert catalog.generator == "beam"
    assert catalog.heroes[13].generator["effective"] == effective
    require_generator("beam", catalog.generator)
    with pytest.raises(ArtifactError, match="differs"):
        require_generator("current", catalog.generator)


@pytest.mark.parametrize(
    ("generator", "version"),
    [("current", "eclat-leiden-pairwise-v3"), ("beam", "eclat-leiden-beam16-v1")],
)
def test_rejects_evidence_from_previous_sql_validation_rules(
    tmp_path: Path, generator: str, version: str
) -> None:
    document = make_beam_document() if generator == "beam" else make_evidence_document()
    require_object_dict(document["method"])["version"] = version
    path = tmp_path / "previous-method.json"
    write_fingerprinted_evidence(path, document)
    with pytest.raises(ArtifactError, match="unsupported selection method"):
        load_build_evidence(path)


@pytest.mark.parametrize("value", [None, {}, {"name": "beam"}])
def test_rejects_incomplete_generator_header(value: object) -> None:
    with pytest.raises(ArtifactError, match="settings or version"):
        validate_generator_header(value)
    validate_generator_header(generator_record())


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("group_id", "other"),
        ("core", [1]),
        ("variant_id", "wrong"),
        ("effective", "unknown"),
        ("states", []),
        ("states", [1, 1]),
        ("states", [[1]]),
        ("states", [True]),
        ("scores", {}),
        ("scores", {"1": float("nan")}),
        ("scores", {"1": True}),
        ("baseline_path_id", ""),
        ("state_evidence", {}),
        ("frozen_sha256", "bad"),
    ],
)
def test_rejects_inconsistent_path_metadata(key: str, value: object) -> None:
    record = make_generator_path((1, 2, 3, 4), 6, "group")
    record[key] = value
    with pytest.raises(ArtifactError):
        validate_generator_path(record, group="group", core=(1, 2, 3, 4), hero=6)


def test_rejects_small_matched_sample_and_inconsistent_default(tmp_path: Path) -> None:
    document = make_beam_document()
    hero = require_object_rows(document["heroes"])[0]
    build = require_object_rows(hero["builds"])[0]
    record = require_object_dict(build["generator"])
    folds = require_object_dict(require_object_dict(record["state_evidence"])["1"])
    row = require_object_dict(folds["discovery"])
    row.update({"owners": 100, "wins": 55})
    row["lower_95"], row["upper_95"] = wilson_score_interval(55, 100)
    path = tmp_path / "small.json"
    write_fingerprinted_evidence(path, document)
    with pytest.raises(ArtifactError, match="matched discovery support"):
        load_build_evidence(path)
    row.update({"owners": 200, "wins": 110})
    row["lower_95"], row["upper_95"] = wilson_score_interval(110, 200)
    record["default_variant_id"] = "wrong"
    write_fingerprinted_evidence(path, document)
    with pytest.raises(ArtifactError, match="default variant"):
        load_build_evidence(path)


def test_current_header_cannot_hide_beam_paths(tmp_path: Path) -> None:
    document = make_beam_document()
    document["schema_version"] = 12
    require_object_dict(document["method"])["version"] = METHOD_VERSION
    document.pop("generator")
    path = tmp_path / "mixed.json"
    write_fingerprinted_evidence(path, document)
    with pytest.raises(ArtifactError, match="Current evidence"):
        load_build_evidence(path)


@pytest.mark.parametrize("effective", ["current", "beam"])
def test_sequence_generator_must_match_discovery(
    tmp_path: Path, effective: str
) -> None:
    document = make_beam_document(effective=effective)
    build = require_object_rows(require_object_rows(document["heroes"])[0]["builds"])[0]
    require_object_dict(build["sequence_policy"])["production_model"] = (
        "pairwise" if effective == "beam" else "beam16"
    )
    path = tmp_path / "mixed-sequence.json"
    write_fingerprinted_evidence(path, document)
    with pytest.raises(ArtifactError, match="Sequence generator"):
        load_build_evidence(path)


def test_changed_default_retains_group_identity_and_separate_variant_identity() -> None:
    baseline: dict[str, object] = {
        "path_id": "group",
        "core_policy": {"default_item_ids": [1, 2, 3, 4]},
        "discovery": {"hero_id": 6},
    }
    proposed: dict[str, object] = {
        "path_id": "new",
        "core_policy": {"default_item_ids": [1, 2, 3, 5]},
        "discovery": {"hero_id": 6},
        "generator": make_generator_path((1, 2, 3, 5), 6, "group"),
    }
    before = deepcopy(baseline)
    result = assemble_group([baseline], [proposed], "group")
    identity = str(require_object_dict(proposed["generator"])["variant_id"])
    attach_group_metadata(result, "group", identity, "a" * 64, 0)
    assert result[0]["path_id"] == "group"
    assert require_object_dict(result[0]["generator"])["variant_id"] == identity
    assert identity != "group"
    assert baseline == before
    fallback = assemble_group([baseline], [], "group")
    assert require_object_dict(fallback[0]["generator"])["effective"] == "current"
    assert baseline == before


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("owners", -1),
        ("wins", 201),
        ("hero_matches", 199),
        ("win_rate", True),
        ("win_rate", None),
        ("lower_95", 0.9),
        ("upper_95", float("nan")),
        ("hero_win_rate", None),
        ("hero_win_rate", 1.1),
        ("ownership_before_seconds", 1199),
    ],
)
def test_inconsistent_state_statistics_are_rejected(key: str, value: object) -> None:
    row = require_object_dict(
        require_object_dict(make_state_evidence()["1"])["validation"]
    )
    row[key] = value
    with pytest.raises(ArtifactError):
        validate_state_row(row)


def test_empty_state_statistics_have_no_estimated_rate() -> None:
    assert (
        validate_state_row({
            "owners": 0,
            "wins": 0,
            "hero_matches": 0,
            "win_rate": None,
            "hero_win_rate": None,
            "lower_95": None,
            "upper_95": None,
            "ownership_before_seconds": 1200,
        })
        == 0
    )
    with pytest.raises(ArtifactError, match="ownership checkpoint"):
        validate_state_row(None)
    with pytest.raises(ArtifactError, match="empty hero sample"):
        validate_state_row({
            "owners": 0,
            "wins": 0,
            "hero_matches": 0,
            "hero_win_rate": 0.5,
            "ownership_before_seconds": 1200,
        })


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("effective", "current"),
        ("frozen_sha256", "b" * 64),
        ("states", [0]),
    ],
)
def test_generator_group_provenance_is_checked(
    tmp_path: Path, key: str, value: object
) -> None:
    document = make_beam_document()
    build = require_object_rows(require_object_rows(document["heroes"])[0]["builds"])[0]
    metadata = require_object_dict(build["generator"])
    metadata[key] = value
    metadata["fallback_reason"] = "Test fallback"
    path = tmp_path / "mixed-generator.json"
    write_fingerprinted_evidence(path, document)
    with pytest.raises(ArtifactError):
        load_build_evidence(path)
