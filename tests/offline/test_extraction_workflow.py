from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

import duckdb
import polars as pl
import pytest

from deadlock_build_sync.offline import extract as extract_module
from deadlock_build_sync.offline.api import write_json
from deadlock_build_sync.offline.config import Cohort, RunPaths
from tests.offline.sql_fixtures import load_fixture_sql

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

    def execute(self, query: str, _parameters: object = None) -> _FakeConnection:
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

    result = extract_module._connect_analysis_database(
        RunPaths.create(tmp_path, "connect")
    )

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
    monkeypatch.setattr(
        extract_module, "_connect_analysis_database", lambda _paths: _connection(fake)
    )

    counts = extract_module.extract_cohort(paths, _cohort())

    assert counts == {
        "extracted_minimum_badge": 71,
        "source_snapshot_version": 7,
        "player_matches": 7,
        "match_folds": 7,
        "purchases": 7,
        "first_purchases": 7,
        "decision_opportunities": 7,
        "heroes": 7,
        "hero_account_rows": 7,
        "valid_purchase_net_worth": 7,
        "valid_team_lead": 7,
    }
    assert fake.closed
    assert not temporary.exists()
    assert len(fake.inserted) == 1
    assert sum("COPY" in query for query in fake.queries) == 12
    assert any("decision_opportunities" in query for query in fake.queries)


def test_extract_helpers_load_export_count_and_bind_parameters(
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
    extract_module._export_table(connection, "table_name", paths.data / "table.parquet")

    assert list(fake.inserted) == [
        (10, "Item 10", "", 1, 0, "unknown", False, True, "[]")
    ]
    assert (
        extract_module._query_count(connection, load_fixture_sql("select_seven.sql"))
        == 7
    )
    assert extract_module._build_cohort_parameters(_cohort()) == {
        "match_mode": "Ranked",
        "game_mode": "Normal",
        "since": _cohort().since,
        "as_of": _cohort().as_of,
        "minimum_badge": 71,
        "maximum_badge": 115,
    }

    empty = _connection(_FakeConnection(row=None))
    with pytest.raises(RuntimeError, match="returned no row"):
        extract_module._query_count(empty, load_fixture_sql("select_zero.sql"))


def test_remote_query_rejects_fatal_and_exhausted_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(extract_module.time, "sleep", lambda _delay: None)
    fatal = _connection(_FakeConnection(failures=[duckdb.Error("fatal")]))
    with pytest.raises(duckdb.Error, match="fatal"):
        extract_module._execute_remote_query(fatal, load_fixture_sql("select_one.sql"))

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
        extract_module._execute_remote_query(
            exhausted, load_fixture_sql("select_one.sql")
        )


def test_sql_files_extract_and_export_complete_cohort(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = RunPaths.create(tmp_path, "complete-extraction")
    write_json(
        paths.raw / "items.json",
        [{"id": 10, "item_tier": 1}, {"id": 20, "item_tier": 2}],
    )

    def connect_source(paths: RunPaths) -> duckdb.DuckDBPyConnection:
        connection = duckdb.connect(str(paths.raw / "analysis.duckdb"))
        connection.execute(load_fixture_sql("extract/create_source_tables.sql"))
        return connection

    monkeypatch.setattr(extract_module, "_connect_analysis_database", connect_source)
    counts = extract_module.extract_cohort(paths, _cohort())
    assert counts == {
        "player_matches": 360,
        "match_folds": 30,
        "purchases": 1080,
        "first_purchases": 720,
        "decision_opportunities": 720,
        "source_snapshot_version": 7,
        "extracted_minimum_badge": 71,
        "heroes": 12,
        "hero_account_rows": 12,
        "valid_purchase_net_worth": 720,
        "valid_team_lead": 720,
    }
    exports = sorted(paths.data.glob("*.parquet"))
    assert len(exports) == 12
    with duckdb.connect(
        str(paths.raw / "analysis.duckdb"), read_only=True
    ) as connection:
        for path in exports:
            exported = pl.read_parquet(path)
            assert exported.height == connection.table(path.stem).shape[0]
    purchases = pl.read_parquet(paths.data / "purchases.parquet").filter(
        (pl.col("match_id") == 1) & (pl.col("player_slot") == 0)
    )
    assert purchases.select(
        "item_id", "buy_time", "event_order", "item_purchase_ordinal"
    ).rows() == [(10, 100, 1, 1), (20, 600, 2, 1), (10, 900, 3, 2)]
