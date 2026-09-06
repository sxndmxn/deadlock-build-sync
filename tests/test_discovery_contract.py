from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING

import pytest

from deadlock_build_sync.artifacts import ArtifactError
from deadlock_build_sync.build_evidence import load_build_evidence
from deadlock_build_sync.build_evidence_discovery import exclusion_reason
from deadlock_build_sync.value_validation import require_object_rows
from tests.build_evidence_fixtures import _document, _refingerprint, _write

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
