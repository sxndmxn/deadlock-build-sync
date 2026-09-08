from __future__ import annotations

import json
from typing import TYPE_CHECKING

import duckdb
import pytest

from deadlock_build_sync.offline import discovery_export as producer
from deadlock_build_sync.offline.config import RunPaths
from deadlock_build_sync.offline.discovery_snapshot import (
    load_discovery_snapshot,
    save_discovery_snapshot,
)
from deadlock_build_sync.snapshot import sha256_json
from tests.offline.discovery_fixtures import make_hero_discovery_data
from tests.offline.production_evidence_fixtures import make_export_context

if TYPE_CHECKING:
    from pathlib import Path

    from deadlock_build_sync.offline.discovery_data import HeroDiscoveryData
    from deadlock_build_sync.offline.discovery_types import FrozenHeroDiscovery
    from deadlock_build_sync.offline.production_sources import _HeroExportContext


def _frozen_report() -> FrozenHeroDiscovery:
    return {
        "rows": [
            {
                "identity_id": "build",
                "items": [1, 2, 3],
                "selection_rank": 0,
                "branch_candidates": [],
            }
        ],
        "cohort": {"minimum_badge": 71, "maximum_badge": 115},
        "candidate_count": 1,
        "candidates": [],
        "grouping": {"groups": [], "seeds": [], "edges": [], "candidate_order": []},
    }


def test_resume_preserves_candidates_groups_and_family_without_discovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = RunPaths.create(tmp_path, "resume")
    duckdb.connect(str(paths.raw / "analysis.duckdb")).close()
    frozen = {hero: _frozen_report() for hero in (6, 10)}
    groups = {hero: {"build": "build"} for hero in frozen}
    save_discovery_snapshot(paths, frozen, groups)
    previous = {path: path.read_bytes() for path in paths.run.glob("*.json")}
    heroes: list[dict[str, object]] = [
        {"id": hero, "name": f"Hero {hero}"} for hero in frozen
    ]
    monkeypatch.setattr(producer, "prepare_discovery_partitions", lambda _cursor: None)
    monkeypatch.setattr(
        producer, "load_hero_discovery_data", lambda *_args: make_hero_discovery_data()
    )

    def reject_discovery(_job: producer.HeroDiscoveryJob) -> FrozenHeroDiscovery:
        raise AssertionError("Resume must not repeat discovery")

    def validate_hero(
        _connection: duckdb.DuckDBPyConnection,
        hero: dict[str, object],
        entry: tuple[HeroDiscoveryData, FrozenHeroDiscovery],
        _context: _HeroExportContext,
        family: producer.ValidationFamily,
    ) -> dict[str, object]:
        assert entry[1] == _frozen_report()
        assert family == producer.ValidationFamily(2, 1, sha256_json(frozen))
        return {"hero_id": hero["id"], "builds": [{"path_id": "build"}]}

    monkeypatch.setattr(producer, "_run_discovery_job", reject_discovery)
    monkeypatch.setattr(producer, "_validate_hero", validate_hero)
    result = producer.discover_hero_roster(
        heroes, make_export_context(paths), workers=1, resume=True
    )
    assert [row["hero_id"] for row in result] == [6, 10]
    assert result[0]["builds"] == [{"path_id": "build", "guide_group_id": "build"}]
    assert {path: path.read_bytes() for path in previous} == previous


@pytest.mark.parametrize("count", [0, 2])
def test_resume_rejects_missing_or_ambiguous_snapshot(
    tmp_path: Path, count: int
) -> None:
    paths = RunPaths.create(tmp_path, "missing")
    for index in range(count):
        (paths.run / f"discovery-nominations-{index}.json").write_text("{}")
    with pytest.raises(ValueError, match="one complete discovery snapshot"):
        load_discovery_snapshot(paths, [])


@pytest.mark.parametrize("damage", ["hero", "candidates", "groups", "missing_groups"])
def test_resume_rejects_incomplete_or_modified_snapshot(
    tmp_path: Path, damage: str
) -> None:
    paths = RunPaths.create(tmp_path, "modified")
    frozen = {6: _frozen_report()}
    save_discovery_snapshot(paths, frozen, {6: {"build": "build"}})
    heroes: list[dict[str, object]] = [{"id": 6}]
    if damage == "hero":
        heroes.append({"id": 10})
    elif damage == "candidates":
        frozen[6]["candidate_count"] = 2
        next(paths.run.glob("discovery-nominations-*.json")).write_text(
            json.dumps(frozen)
        )
    elif damage == "groups":
        next(paths.run.glob("guide-groups-*.json")).write_text("{}")
    else:
        next(paths.run.glob("guide-groups-*.json")).unlink()
    with pytest.raises((ValueError, FileNotFoundError)):
        load_discovery_snapshot(paths, heroes)
