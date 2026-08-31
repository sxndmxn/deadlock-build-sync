import copy
import json
import math
from pathlib import Path

import pytest

from deadlock_build_sync.artifacts import ArtifactError
from deadlock_build_sync.build_evidence import (
    load_build_evidence,
    nondecreasing_window_schedule,
)
from deadlock_build_sync.value_validation import (
    require_object_dict,
    require_object_list,
    require_object_rows,
)
from tests.build_evidence_fixtures import (
    _document,
    _first_build,
    _refingerprint,
    _write,
)


def _write_validated(path: Path, document: dict[str, object]) -> None:
    _refingerprint(document)
    _write(path, document)


def test_loader_reports_invalid_json_and_non_object_roots(tmp_path: Path) -> None:
    path = tmp_path / "build-evidence.json"
    path.write_text("{", encoding="utf-8")
    with pytest.raises(ArtifactError, match="could not read"):
        load_build_evidence(path)

    path.write_text(json.dumps([]), encoding="utf-8")
    with pytest.raises(ArtifactError, match="root must be an object"):
        load_build_evidence(path)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("method", None, "unsupported selection method"),
        ("heroes", None, "incomplete identity header"),
        ("requested_hero_ids", None, "incomplete identity header"),
        ("patch", None, "incomplete identity header"),
        ("patch", {"identity": 7}, "incomplete identity header"),
        ("cohort", None, "incomplete identity header"),
        ("epochs", None, "incomplete identity header"),
    ],
)
def test_loader_rejects_incomplete_headers(
    tmp_path: Path,
    field: str,
    value: object,
    message: str,
) -> None:
    document = _document()
    document[field] = value
    path = tmp_path / "build-evidence.json"
    _write_validated(path, document)

    with pytest.raises(ArtifactError, match=message):
        load_build_evidence(path)


@pytest.mark.parametrize(
    ("epoch", "value", "message"),
    [
        ("mechanics", None, "lacks the mechanics epoch"),
        (
            "matchmaking",
            {"identity": 7, "start_timestamp": 1_700_000_000},
            "invalid matchmaking epoch",
        ),
        (
            "telemetry",
            {"identity": "epoch", "start_timestamp": -1},
            "telemetry epoch timestamp",
        ),
    ],
)
def test_loader_rejects_invalid_epoch_records(
    tmp_path: Path,
    epoch: str,
    value: object,
    message: str,
) -> None:
    document = _document()
    epochs = require_object_dict(document["epochs"])
    epochs[epoch] = value
    path = tmp_path / "build-evidence.json"
    _write_validated(path, document)

    with pytest.raises(ArtifactError, match=message):
        load_build_evidence(path)


def test_loader_rejects_duplicate_or_mismatched_hero_sets(tmp_path: Path) -> None:
    path = tmp_path / "build-evidence.json"
    duplicate_hero = _document()
    heroes = require_object_list(duplicate_hero["heroes"])
    heroes.append(copy.deepcopy(heroes[0]))
    _write_validated(path, duplicate_hero)
    with pytest.raises(ArtifactError, match="duplicate heroes"):
        load_build_evidence(path)

    duplicate_request = _document()
    duplicate_request["requested_hero_ids"] = [13, 13]
    _write_validated(path, duplicate_request)
    with pytest.raises(ArtifactError, match="duplicate requested"):
        load_build_evidence(path)

    missing_request = _document()
    missing_request["requested_hero_ids"] = [14]
    _write_validated(path, missing_request)
    with pytest.raises(ArtifactError, match="exactly cover"):
        load_build_evidence(path)


@pytest.mark.parametrize(
    ("as_of", "message"),
    [
        (7, "no frozen as-of"),
        ("not-a-date", "invalid as-of"),
        ("2026-08-09T00:00:00", "lacks a timezone"),
        ("2020-01-01T00:00:00+00:00", "precedes an epoch"),
    ],
)
def test_loader_rejects_invalid_as_of_cutoffs(
    tmp_path: Path,
    as_of: object,
    message: str,
) -> None:
    document = _document()
    cohort = require_object_dict(document["cohort"])
    cohort["as_of"] = as_of
    path = tmp_path / "build-evidence.json"
    _write_validated(path, document)

    with pytest.raises(ArtifactError, match=message):
        load_build_evidence(path)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("path_id", ""),
        ("path_label", 7),
        ("signature_item_ids", None),
        ("signature_item_ids", [0]),
        ("signature_item_ids", [101, 101]),
        ("discovery", []),
    ],
)
def test_loader_rejects_invalid_build_path_identity(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    document = _document()
    _first_build(document)[field] = value
    path = tmp_path / "build-evidence.json"
    _write_validated(path, document)

    with pytest.raises(ArtifactError, match="invalid build path identity"):
        load_build_evidence(path)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"fold_eligible_player_matches": None}, "lacks fold cohort"),
        (
            {
                "fold_eligible_player_matches": {
                    "train": 599,
                    "validation": 200,
                    "test": 200,
                }
            },
            "inconsistent fold cohort",
        ),
        ({"selection_eligible_player_matches": 799}, "inconsistent fold cohort"),
        ({"items": None}, "incomplete build evidence"),
    ],
)
def test_loader_rejects_invalid_path_cohorts_or_items(
    tmp_path: Path,
    changes: dict[str, object],
    message: str,
) -> None:
    document = _document()
    _first_build(document).update(changes)
    path = tmp_path / "build-evidence.json"
    _write_validated(path, document)

    with pytest.raises(ArtifactError, match=message):
        load_build_evidence(path)


def test_loader_rejects_item_fold_denominator_drift(tmp_path: Path) -> None:
    document = _document()
    build = _first_build(document)
    build["fold_eligible_player_matches"] = {
        "train": 599,
        "validation": 201,
        "test": 200,
    }
    path = tmp_path / "build-evidence.json"
    _write_validated(path, document)

    with pytest.raises(ArtifactError, match="item fold denominators disagree"):
        load_build_evidence(path)


def test_loader_rejects_malformed_heroes_and_duplicate_paths(tmp_path: Path) -> None:
    path = tmp_path / "build-evidence.json"
    malformed = _document()
    malformed["heroes"] = [7]
    _write_validated(path, malformed)
    with pytest.raises(ArtifactError, match="malformed hero"):
        load_build_evidence(path)

    no_name = _document()
    require_object_rows(no_name["heroes"])[0]["hero"] = ""
    _write_validated(path, no_name)
    with pytest.raises(ArtifactError, match="has no name"):
        load_build_evidence(path)

    no_builds = _document()
    require_object_rows(no_builds["heroes"])[0]["builds"] = []
    _write_validated(path, no_builds)
    with pytest.raises(ArtifactError, match="no supported build paths"):
        load_build_evidence(path)

    duplicate_paths = _document()
    hero = require_object_rows(duplicate_paths["heroes"])[0]
    builds = require_object_list(hero["builds"])
    builds.append(copy.deepcopy(builds[0]))
    _write_validated(path, duplicate_paths)
    with pytest.raises(ArtifactError, match="duplicate build paths"):
        load_build_evidence(path)


def test_window_schedule_rejects_invalid_and_crossing_intervals() -> None:
    assert nondecreasing_window_schedule((1,), {1: (math.inf, math.inf)}) is None
    assert nondecreasing_window_schedule((1,), {1: (2.0, 1.0)}) is None
    assert (
        nondecreasing_window_schedule((1, 2), {1: (10.0, 20.0), 2: (0.0, 5.0)}) is None
    )
