from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING

import pytest

from deadlock_build_sync.artifacts import ArtifactError
from deadlock_build_sync.build_evidence import load_build_evidence, select_hero_build
from deadlock_build_sync.build_evidence_discovery import exclusion_reason
from deadlock_build_sync.value_validation import (
    require_object_dict,
    require_object_rows,
)
from tests.build_evidence_fixtures import (
    _document,
    _first_build,
    _refingerprint,
    _write,
)

if TYPE_CHECKING:
    from pathlib import Path


def exclusion() -> dict[str, object]:
    return {
        "code": "no_validated_identity",
        "reason": " Insufficient comparable outcomes ",
        "fold_observations": {"discovery": 200, "selection": 100, "validation": 100},
        "candidate_count": 1,
        "candidate_rejections": [{"path_id": "core", "reasons": ["weak win evidence"]}],
    }


def _multiple_builds(count: int = 5) -> dict[str, object]:
    document = _document()
    hero = require_object_rows(document["heroes"])[0]
    builds = []
    for rank in range(count):
        build = _first_build(
            _document(default_item_ids=[101, 102, 201, 202, 301, 302 + rank])
        )
        build["path_id"] = f"core-{rank}"
        build["guide_group_id"] = f"core-{rank}"
        require_object_dict(build["discovery"])["selection_rank"] = rank
        builds.append(build)
    hero["builds"] = builds
    history = require_object_rows(
        require_object_dict(hero["cohort"])["expansion_history"]
    )
    history[-1].update({"supported_builds": count, "candidate_count": count})
    return document


@pytest.mark.parametrize("count", [4, 8])
def test_catalog_loads_every_supported_identity(tmp_path: Path, count: int) -> None:
    document = _multiple_builds(count)
    path = tmp_path / "evidence.json"
    _refingerprint(document)
    _write(path, document)
    catalog = load_build_evidence(path)
    builds = catalog.hero_builds[13]
    assert len(builds) == count
    assert catalog.heroes[13].path_id == "core-0"
    assert [build.path_id for build in builds] == [
        f"core-{rank}" for rank in range(count)
    ]
    for rank, build in enumerate(builds):
        selected = select_hero_build(build, list(catalog.assets))
        assert selected.core[-1].item_id == 302 + rank


@pytest.mark.parametrize(
    ("fault", "error"),
    [
        ("path", "duplicate build paths"),
        ("core", "duplicate identities"),
        ("rank", "duplicate identities or selection ranks"),
        ("exclusion", "conflicting build admission"),
    ],
)
def test_uncapped_catalog_keeps_identity_and_admission_checks(
    tmp_path: Path, fault: str, error: str
) -> None:
    document = _multiple_builds()
    hero = require_object_rows(document["heroes"])[0]
    builds = require_object_rows(hero["builds"])
    if fault == "path":
        builds[-1]["path_id"] = builds[0]["path_id"]
    elif fault == "core":
        builds[-1] = {**deepcopy(builds[0]), "path_id": "different-path"}
        require_object_dict(builds[-1]["discovery"])["selection_rank"] = 4
    elif fault == "rank":
        require_object_dict(builds[-1]["discovery"])["selection_rank"] = 0
    else:
        hero["exclusion"] = exclusion()
    hero["builds"] = builds
    path = tmp_path / "evidence.json"
    _refingerprint(document)
    _write(path, document)
    with pytest.raises(ArtifactError, match=error):
        load_build_evidence(path)


def test_capped_method_requires_refresh(tmp_path: Path) -> None:
    document = _document()
    require_object_dict(document["method"])["version"] = "eclat-leiden-pairwise-v1"
    path = tmp_path / "evidence.json"
    _refingerprint(document)
    _write(path, document)
    with pytest.raises(
        ArtifactError, match=r"unsupported selection method.*refresh-evidence"
    ):
        load_build_evidence(path)


@pytest.mark.parametrize(
    "change",
    [
        {"code": "missing_data"},
        {"reason": ""},
        {"fold_observations": None},
        {"candidate_count": -1},
        {"candidate_rejections": None},
        {"candidate_rejections": []},
        {"candidate_rejections": [{}]},
    ],
)
def test_exclusions_require_observations_and_reasons(change: dict[str, object]) -> None:
    with pytest.raises(ArtifactError):
        exclusion_reason({**exclusion(), **change})
    assert exclusion_reason(exclusion()) == "Insufficient comparable outcomes"
    assert exclusion_reason({
        **exclusion(),
        "candidate_count": 0,
        "candidate_rejections": [],
    })


def test_catalog_preserves_excluded_heroes_and_rejects_missing_disposition(
    tmp_path: Path,
) -> None:
    document = _document()
    hero = require_object_rows(document["heroes"])[0]
    skipped = {"hero_id": 12, "hero": "Kelvin", "builds": [], "exclusion": exclusion()}
    document["heroes"] = [hero, skipped]
    document["requested_hero_ids"] = [13, 12]
    path = tmp_path / "evidence.json"
    _refingerprint(document)
    _write(path, document)
    catalog = load_build_evidence(path)
    assert 13 in catalog.heroes
    assert catalog.exclusions == {12: "Insufficient comparable outcomes"}
    malformed = deepcopy(document)
    require_object_rows(malformed["heroes"])[1].pop("exclusion")
    _refingerprint(malformed)
    _write(path, malformed)
    with pytest.raises(ArtifactError, match="supported exclusion"):
        load_build_evidence(path)
