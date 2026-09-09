from __future__ import annotations

import json
from typing import TYPE_CHECKING

import duckdb
import pytest

from deadlock_build_sync.offline import discovery_export as producer
from deadlock_build_sync.offline.config import RunPaths
from deadlock_build_sync.offline.discovery_snapshot import (
    calculate_discovery_source_identity,
    load_discovery_snapshot,
    save_discovery_snapshot,
)
from deadlock_build_sync.snapshot import sha256_json
from tests.offline.discovery_fixtures import make_hero_discovery_data
from tests.offline.production_evidence_fixtures import (
    make_export_context,
    write_discovery_source_files,
)

if TYPE_CHECKING:
    from pathlib import Path

    from deadlock_build_sync.offline.discovery_data import HeroDiscoveryData
    from deadlock_build_sync.offline.discovery_types import FrozenHeroDiscovery


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
    write_discovery_source_files(paths)
    frozen = {hero: _frozen_report() for hero in (6, 10)}
    groups = {hero: {"build": "build"} for hero in frozen}
    save_discovery_snapshot(
        paths, frozen, groups, calculate_discovery_source_identity(paths)
    )
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
        job: producer.HeroValidationJob,
        _values: HeroDiscoveryData,
    ) -> dict[str, object]:
        assert job.report == _frozen_report()
        assert job.family == producer.ValidationFamily(2, 1, sha256_json(frozen))
        return {"hero_id": job.hero["id"], "builds": [{"path_id": "build"}]}

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
    (paths.raw / "analysis.duckdb").write_bytes(b"database")
    write_discovery_source_files(paths)
    frozen = {6: _frozen_report()}
    save_discovery_snapshot(
        paths,
        frozen,
        {6: {"build": "build"}},
        calculate_discovery_source_identity(paths),
    )
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


@pytest.mark.parametrize(
    "source",
    [
        "manifest.json",
        "raw/analysis.duckdb",
        "raw/heroes.json",
        "raw/items.json",
        "raw/items-all.json",
        "raw/ranks.json",
        "raw/patches.json",
    ],
)
@pytest.mark.parametrize("change", ["modify", "remove"])
def test_resume_rejects_changed_discovery_sources(
    tmp_path: Path, source: str, change: str
) -> None:
    paths = RunPaths.create(tmp_path, "changed-source")
    (paths.raw / "analysis.duckdb").write_bytes(b"database")
    write_discovery_source_files(paths)
    frozen = {6: _frozen_report()}
    save_discovery_snapshot(
        paths,
        frozen,
        {6: {"build": "build"}},
        calculate_discovery_source_identity(paths),
    )
    if change == "modify":
        (paths.run / source).write_text('{"changed": true}')
    else:
        (paths.run / source).unlink()
    with pytest.raises((ValueError, FileNotFoundError)):
        load_discovery_snapshot(paths, [{"id": 6}])


@pytest.mark.parametrize("change", ["legacy", "schema", "method"])
def test_resume_rejects_incompatible_source_identity(
    tmp_path: Path, change: str
) -> None:
    paths = RunPaths.create(tmp_path, "incompatible-source")
    (paths.raw / "analysis.duckdb").write_bytes(b"database")
    write_discovery_source_files(paths)
    frozen = {6: _frozen_report()}
    identity = calculate_discovery_source_identity(paths)
    save_discovery_snapshot(paths, frozen, {6: {"build": "build"}}, identity)
    group_path = next(paths.run.glob("guide-groups-*.json"))
    document = json.loads(group_path.read_text())
    if change == "legacy":
        del document["source_identity"]
    else:
        document["source_identity"][f"{change}_version"] = "incompatible"
    group_path.write_text(json.dumps(document))
    with pytest.raises(ValueError, match=r"source identity.*new --run-id"):
        load_discovery_snapshot(paths, [{"id": 6}])


def test_snapshot_rejects_source_change_during_discovery(tmp_path: Path) -> None:
    paths = RunPaths.create(tmp_path, "source-change")
    (paths.raw / "analysis.duckdb").write_bytes(b"database")
    write_discovery_source_files(paths)
    identity = calculate_discovery_source_identity(paths)
    (paths.run / "manifest.json").write_text('{"snapshot": "changed"}')
    with pytest.raises(ValueError, match="source identity"):
        save_discovery_snapshot(
            paths, {6: _frozen_report()}, {6: {"build": "build"}}, identity
        )
    assert list(paths.run.glob("discovery-nominations-*.json")) == []
    assert list(paths.run.glob("guide-groups-*.json")) == []


@pytest.mark.parametrize("changed_before_validation", [False, True])
def test_resume_checks_sources_before_and_after_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    changed_before_validation: bool,
) -> None:
    paths = RunPaths.create(tmp_path, "validation-source")
    (paths.raw / "analysis.duckdb").write_bytes(b"database")
    write_discovery_source_files(paths)
    frozen = {6: _frozen_report()}
    save_discovery_snapshot(
        paths,
        frozen,
        {6: {"build": "build"}},
        calculate_discovery_source_identity(paths),
    )
    previous = {path: path.read_bytes() for path in paths.run.glob("*-*.json")}
    changed = paths.raw / "items.json"
    if changed_before_validation:
        changed.write_text('[{"id": 99}]')

    def validate_hero(_job: producer.HeroValidationJob) -> dict[str, object]:
        assert not changed_before_validation
        changed.write_text('[{"id": 99}]')
        return {"hero_id": 6, "builds": [{"path_id": "build"}]}

    monkeypatch.setattr(producer, "_run_validation_job", validate_hero)
    with pytest.raises(ValueError, match="source identity"):
        producer.discover_hero_roster(
            [{"id": 6}], make_export_context(paths), workers=1, resume=True
        )
    assert {path: path.read_bytes() for path in previous} == previous
