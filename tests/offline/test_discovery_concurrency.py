from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from multiprocessing import get_context
from threading import Barrier
from typing import TYPE_CHECKING

import duckdb
import pytest
from threadpoolctl import threadpool_info

from deadlock_build_sync.offline import discovery_export as producer
from deadlock_build_sync.offline.config import RunPaths
from deadlock_build_sync.offline.discovery_data import prepare_discovery_partitions
from deadlock_build_sync.offline.discovery_workers import map_discovery_jobs
from deadlock_build_sync.snapshot import sha256_json
from tests.offline.discovery_fixtures import make_hero_discovery_data
from tests.offline.production_evidence_fixtures import (
    make_export_context,
    write_discovery_source_files,
)
from tests.offline.sql_fixtures import load_fixture_sql

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from deadlock_build_sync.offline.discovery_data import HeroDiscoveryData
    from deadlock_build_sync.offline.discovery_types import (
        DiscoveryItemCatalog,
        FrozenHeroDiscovery,
    )
    from deadlock_build_sync.offline.production_sources import _HeroExportContext


def _read_hero_database(job: tuple[RunPaths, int, Barrier]) -> tuple[int, int]:
    paths, hero, barrier = job
    with producer._open_discovery_database(make_export_context(paths)) as connection:
        prepare_discovery_partitions(connection)
        connection.execute(
            load_fixture_sql("concurrency/create_current_hero.sql"), [hero]
        )
        connection.execute(load_fixture_sql("concurrency/set_memory_limit.sql"))
        connection.execute(
            load_fixture_sql("concurrency/create_worker_records.sql"),
            [str(hero)],
        )
        barrier.wait()
        assert connection.execute(
            load_fixture_sql("concurrency/select_current_hero.sql")
        ).fetchone() == (hero,)
        assert connection.execute(
            load_fixture_sql("select_discovery_partitions.sql")
        ).fetchall() == [(1, "discovery"), (2, "selection"), (3, "validation")]
        assert connection.execute(
            load_fixture_sql("concurrency/count_invalid_records.sql"),
            [str(hero)],
        ).fetchone() == (0,)
    return os.getpid(), hero


def test_eight_processes_isolate_connections_and_preserve_result_order(
    tmp_path: Path,
) -> None:
    paths = RunPaths.create(tmp_path, "worker-database")
    database = str(paths.raw / "analysis.duckdb")
    with duckdb.connect(database) as connection:
        connection.execute(load_fixture_sql("concurrency/create_player_matches.sql"))
        connection.execute(load_fixture_sql("concurrency/create_match_folds.sql"))
    with get_context("spawn").Manager() as manager:
        barrier = manager.Barrier(8, timeout=30)
        results = map_discovery_jobs(
            _read_hero_database, [(paths, hero, barrier) for hero in range(16)], 8
        )
    assert [hero for _, hero in results] == list(range(16))
    assert len({process for process, _ in results}) == 8
    assert os.getpid() not in {process for process, _ in results}
    with duckdb.connect(database) as connection:
        connection.execute(load_fixture_sql("concurrency/create_after_workers.sql"))


def _reject_hero_job(_hero: int) -> int:
    raise ValueError("Invalid hero evidence")


def test_process_failure_reaches_caller() -> None:
    with pytest.raises(ValueError, match="Invalid hero evidence"):
        map_discovery_jobs(_reject_hero_job, [1], 2)
    with pytest.raises(ValueError, match="at least 1"):
        map_discovery_jobs(_reject_hero_job, [1], 0)


def test_worker_failure_closes_connection_and_restores_native_limits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = RunPaths.create(tmp_path, "worker-failure")
    duckdb.connect(str(paths.raw / "analysis.duckdb")).close()
    monkeypatch.setattr(producer, "prepare_discovery_partitions", lambda _cursor: None)
    connections: list[duckdb.DuckDBPyConnection] = []
    limits = threadpool_info()

    def reject_hero(
        connection: duckdb.DuckDBPyConnection,
        _hero: dict[str, object],
        _context: _HeroExportContext,
        _catalog: DiscoveryItemCatalog,
    ) -> tuple[HeroDiscoveryData, FrozenHeroDiscovery]:
        connections.append(connection)
        assert all(pool["num_threads"] == 1 for pool in threadpool_info())
        raise ValueError("Invalid hero evidence")

    monkeypatch.setattr(producer, "_freeze_hero", reject_hero)
    with pytest.raises(ValueError, match="Invalid hero evidence"):
        producer._run_discovery_job(
            producer.HeroDiscoveryJob({"id": 1}, make_export_context(paths), {})
        )
    with pytest.raises(duckdb.ConnectionException, match="closed"):
        connections[0].execute(load_fixture_sql("select_one.sql"))
    assert threadpool_info() == limits


def _map_test_calculations[Job, Result](
    operation: Callable[[Job], Result], jobs: list[Job], workers: int
) -> list[Result]:
    # Threads keep the patched calculations visible in this orchestration test.
    with ThreadPoolExecutor(max_workers=workers) as executor:
        return list(executor.map(operation, jobs))


def test_roster_freezes_entire_family_before_eight_concurrent_validations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = RunPaths.create(tmp_path, "concurrent-roster")
    duckdb.connect(str(paths.raw / "analysis.duckdb")).close()
    write_discovery_source_files(paths)
    monkeypatch.setattr(producer, "map_discovery_jobs", _map_test_calculations)
    monkeypatch.setattr(producer, "threadpool_limits", lambda **_kwargs: nullcontext())
    monkeypatch.setattr(producer, "prepare_discovery_partitions", lambda _cursor: None)
    monkeypatch.setattr(
        producer, "load_hero_discovery_data", lambda *_args: make_hero_discovery_data()
    )
    barrier = Barrier(8, timeout=10)
    heroes: list[dict[str, object]] = [
        {"id": index, "name": f"Hero {index}"} for index in range(8)
    ]

    def freeze_hero_fixture(
        _cursor: duckdb.DuckDBPyConnection,
        hero: dict[str, object],
        _context: _HeroExportContext,
        _catalog: DiscoveryItemCatalog,
    ) -> tuple[HeroDiscoveryData, FrozenHeroDiscovery]:
        barrier.wait()
        return make_hero_discovery_data(), {
            "rows": [
                {
                    "identity_id": str(hero["id"]),
                    "items": [1, 2, 3],
                    "selection_rank": 0,
                    "branch_candidates": [{}, {}],
                }
            ],
            "cohort": {"minimum_badge": 71, "maximum_badge": 115},
            "candidate_count": 1,
            "candidates": [],
            "grouping": {"groups": [], "seeds": [], "edges": [], "candidate_order": []},
        }

    def validate_hero_fixture(
        _cursor: duckdb.DuckDBPyConnection,
        job: producer.HeroValidationJob,
        _values: HeroDiscoveryData,
    ) -> dict[str, object]:
        barrier.wait()
        frozen_path = next(paths.run.glob("discovery-nominations-*.json"))
        frozen = json.loads(frozen_path.read_text())
        assert len(frozen) == 8
        assert job.family == producer.ValidationFamily(8, 16, sha256_json(frozen))
        groups = json.loads(next(paths.run.glob("guide-groups-*.json")).read_text())
        assert len(groups["groups"]) == 8
        assert groups["frozen_sha256"] == job.family.frozen_hash
        hero = job.hero
        return {"hero_id": hero["id"], "builds": [{"path_id": str(hero["id"])}]}

    monkeypatch.setattr(producer, "_freeze_hero", freeze_hero_fixture)
    monkeypatch.setattr(producer, "_validate_hero", validate_hero_fixture)
    results = producer.discover_hero_roster(heroes, make_export_context(paths))
    assert [result["hero_id"] for result in results] == list(range(8))
    assert [result["builds"] for result in results] == [
        [{"path_id": str(index), "guide_group_id": str(index)}] for index in range(8)
    ]
