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
from tests.offline.production_evidence_fixtures import make_export_context

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
        connection.execute("CREATE TEMP TABLE current_hero AS SELECT ? AS id", [hero])
        connection.execute("SET memory_limit='16MiB'")
        connection.execute(
            """
            CREATE TEMP TABLE worker_records AS
            SELECT range AS id, repeat(md5(? || ':' || range::VARCHAR), 4) AS payload
            FROM range(300000)
        """,
            [str(hero)],
        )
        barrier.wait()
        assert connection.execute("SELECT id FROM current_hero").fetchone() == (hero,)
        assert connection.execute(
            "SELECT * FROM discovery_partitions ORDER BY match_id"
        ).fetchall() == [(1, "discovery"), (2, "selection"), (3, "validation")]
        assert connection.execute(
            """
            SELECT count(*) FROM worker_records
            WHERE payload != repeat(md5(? || ':' || id::VARCHAR), 4)
        """,
            [str(hero)],
        ).fetchone() == (0,)
    return os.getpid(), hero


def test_eight_processes_isolate_connections_and_preserve_result_order(
    tmp_path: Path,
) -> None:
    paths = RunPaths.create(tmp_path, "worker-database")
    database = str(paths.raw / "analysis.duckdb")
    with duckdb.connect(database) as connection:
        connection.execute("""
            CREATE TABLE player_matches AS
            SELECT * FROM (VALUES (1, 1), (2, 2), (3, 3), (4, 4))
                AS matches(match_id, start_time)
        """)
        connection.execute("""
            CREATE TABLE match_folds AS
            SELECT * FROM (VALUES (1, 'train'), (2, 'train'), (3, 'validation'), (4, 'test'))
                AS folds(match_id, fold)
        """)
    with get_context("spawn").Manager() as manager:
        barrier = manager.Barrier(8, timeout=30)
        results = map_discovery_jobs(
            _read_hero_database, [(paths, hero, barrier) for hero in range(16)], 8
        )
    assert [hero for _, hero in results] == list(range(16))
    assert len({process for process, _ in results}) == 8
    assert os.getpid() not in {process for process, _ in results}
    with duckdb.connect(database) as connection:
        connection.execute("CREATE TABLE after_workers AS SELECT 1 AS value")


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
        connections[0].execute("SELECT 1")
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
        hero: dict[str, object],
        _entry: tuple[HeroDiscoveryData, FrozenHeroDiscovery],
        _context: _HeroExportContext,
        family: producer.ValidationFamily,
    ) -> dict[str, object]:
        barrier.wait()
        frozen_path = next(paths.run.glob("discovery-nominations-*.json"))
        frozen = json.loads(frozen_path.read_text())
        assert len(frozen) == 8
        assert family == producer.ValidationFamily(8, 16, sha256_json(frozen))
        groups = json.loads(next(paths.run.glob("guide-groups-*.json")).read_text())
        assert len(groups["groups"]) == 8
        assert groups["frozen_sha256"] == family.frozen_hash
        return {"hero_id": hero["id"], "builds": [{"path_id": str(hero["id"])}]}

    monkeypatch.setattr(producer, "_freeze_hero", freeze_hero_fixture)
    monkeypatch.setattr(producer, "_validate_hero", validate_hero_fixture)
    results = producer.discover_hero_roster(heroes, make_export_context(paths))
    assert [result["hero_id"] for result in results] == list(range(8))
    assert [result["builds"] for result in results] == [
        [{"path_id": str(index), "guide_group_id": str(index)}] for index in range(8)
    ]
