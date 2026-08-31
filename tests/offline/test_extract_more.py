from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

import duckdb
import pytest

from deadlock_build_sync.offline import extract as extract_module
from deadlock_build_sync.offline.api import write_json
from deadlock_build_sync.offline.config import Cohort, RunPaths

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path


class _FakeConnection:
    def __init__(
        self,
        *,
        row: tuple[object, ...] | None = (7,),
        failures: list[duckdb.Error] | None = None,
    ) -> None:
        self.row = row
        self.failures = list(failures or [])
        self.queries: list[str] = []
        self.inserted: Sequence[Sequence[object]] = ()
        self.closed = False

    def execute(self, query: str) -> _FakeConnection:
        self.queries.append(query)
        if self.failures:
            raise self.failures.pop(0)
        return self

    def executemany(
        self,
        _query: str,
        values: Sequence[Sequence[object]],
    ) -> _FakeConnection:
        self.inserted = values
        return self

    def fetchone(self) -> tuple[object, ...] | None:
        return self.row

    def close(self) -> None:
        self.closed = True


def _connection(fake: _FakeConnection) -> duckdb.DuckDBPyConnection:
    return cast("duckdb.DuckDBPyConnection", fake)


def _cohort() -> Cohort:
    return Cohort(
        since=datetime(2026, 8, 1, tzinfo=UTC),
        as_of=datetime(2026, 8, 2, tzinfo=UTC),
    )


def test_connect_configures_local_and_remote_duckdb(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeConnection()
    monkeypatch.setattr(
        extract_module.duckdb,
        "connect",
        lambda _path: _connection(fake),
    )

    result = extract_module._connect(RunPaths.create(tmp_path, "connect"))

    assert result is _connection(fake)
    assert any("memory_limit" in query for query in fake.queries)
    assert any("ATTACH" in query for query in fake.queries)


def test_extract_cohort_runs_all_stages_exports_and_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = RunPaths.create(tmp_path, "extract")
    write_json(
        paths.raw / "items.json",
        [
            {
                "id": 10,
                "name": "Item",
                "class_name": "item_10",
                "item_tier": 1,
                "cost": 500,
                "item_slot_type": "Weapon",
                "is_active_item": False,
                "is_unique": True,
                "component_items": [],
            }
        ],
    )
    temporary = paths.raw / "duckdb-tmp"
    temporary.mkdir()
    (temporary / "work").touch()
    fake = _FakeConnection()
    monkeypatch.setattr(extract_module, "_connect", lambda _paths: _connection(fake))

    counts = extract_module.extract_cohort(paths, _cohort())

    assert all(value == 7 for value in counts.values())
    assert fake.closed
    assert not temporary.exists()
    assert len(fake.inserted) == 1
    assert sum("COPY" in query for query in fake.queries) == 10
    assert any("decision_opportunities" in query for query in fake.queries)


def test_extract_helpers_load_export_count_and_format(
    tmp_path: Path,
) -> None:
    paths = RunPaths.create(tmp_path, "helpers")
    write_json(
        paths.raw / "items.json",
        [{"id": 10, "item_tier": 1}],
    )
    fake = _FakeConnection()
    connection = _connection(fake)

    extract_module._load_item_assets(connection, paths.raw / "items.json")
    extract_module._export(connection, "table_name", paths.data / "table.parquet")

    assert len(fake.inserted) == 1
    assert fake.inserted[0][1] == "Item 10"
    assert extract_module._count(connection, "SELECT 7") == 7
    assert extract_module._sql_timestamp(_cohort().since).endswith("+00")
    assert "average_badge BETWEEN 71 AND 115" in extract_module._cohort_where(_cohort())

    empty = _connection(_FakeConnection(row=None))
    with pytest.raises(RuntimeError, match="returned no row"):
        extract_module._count(empty, "SELECT 0")


def test_remote_query_rejects_fatal_and_exhausted_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(extract_module.time, "sleep", lambda _delay: None)
    fatal = _connection(_FakeConnection(failures=[duckdb.Error("fatal")]))
    with pytest.raises(duckdb.Error, match="fatal"):
        extract_module._execute_remote_query(fatal, "SELECT 1")

    exhausted = _connection(
        _FakeConnection(
            failures=[
                duckdb.InvalidInputException(
                    "HTTP GET error while reading remote snapshot"
                )
                for _ in range(4)
            ]
        )
    )
    with pytest.raises(duckdb.InvalidInputException, match="HTTP GET"):
        extract_module._execute_remote_query(exhausted, "SELECT 1")
