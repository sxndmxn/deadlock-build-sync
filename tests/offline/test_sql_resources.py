"""Check packaged SQL loading, bound values, and snapshot isolation."""

from __future__ import annotations

from importlib.resources import files
from typing import TYPE_CHECKING

import duckdb
import polars as pl
import pytest

from deadlock_build_sync.offline.extract import _export_table, _query_count
from deadlock_build_sync.offline.sql_resources import load_sql
from tests.offline.sql_fixtures import load_fixture_sql

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(
    "name",
    sorted(
        f"{directory.name}/{query.name}"
        for directory in files("deadlock_build_sync.offline").joinpath("sql").iterdir()
        if directory.is_dir()
        for query in directory.iterdir()
        if query.name.endswith(".sql")
    ),
)
def test_packaged_sql_statements_parse(name: str) -> None:
    with duckdb.connect() as connection:
        assert connection.extract_statements(load_sql(name))


def test_cached_sql_uses_current_parameters_from_another_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    load_sql.cache_clear()
    with duckdb.connect() as connection:
        for version in (7, 12):
            connection.execute(
                load_sql("extract/create_source_snapshot.sql"), {"version": version}
            )
            assert connection.table("source_snapshot").fetchall() == [(version,)]
    assert load_sql.cache_info().misses == 1
    assert load_sql.cache_info().hits == 1
    with pytest.raises(FileNotFoundError):
        load_sql("extract/missing.sql")
    load_sql.cache_clear()


def test_export_binds_table_names_and_paths_with_apostrophes(tmp_path: Path) -> None:
    expected = pl.DataFrame({"value": [7, 12]})
    destination = tmp_path / "player's data.parquet"
    with duckdb.connect() as connection:
        connection.register("records", expected)
        _export_table(connection, "records", destination)
        assert pl.read_parquet(destination).equals(expected)
        assert (
            _query_count(
                connection,
                load_sql("extract/count_table_rows.sql"),
                {"table": "records"},
            )
            == 2
        )
        with pytest.raises(duckdb.Error):
            _query_count(
                connection,
                load_sql("extract/count_table_rows.sql"),
                {"table": "records; DROP VIEW records; --"},
            )
        assert connection.table("records").fetchall() == [(7,), (12,)]


def test_ducklake_parameters_preserve_read_only_snapshot(tmp_path: Path) -> None:
    with duckdb.connect(config={"autoinstall_known_extensions": False}) as connection:
        installed = connection.execute(
            load_fixture_sql("ducklake/select_extension_installed.sql")
        ).fetchone()
        if installed != (True,):
            pytest.skip("The local DuckLake extension is not installed")
        connection.execute(load_fixture_sql("ducklake/load_extension.sql"))
        connection.execute(
            load_sql("extract/create_ducklake_secret.sql"),
            {"metadata_path": str(tmp_path / "player's catalog.ducklake")},
        )
        connection.execute(load_fixture_sql("ducklake/attach_writable.sql"))
        connection.execute(load_fixture_sql("ducklake/create_records.sql"))
        version = _query_count(
            connection, load_sql("extract/select_current_snapshot.sql")
        )
        connection.execute(load_fixture_sql("ducklake/insert_record.sql"))
        connection.execute(load_sql("extract/detach_remote.sql"))
        connection.execute(load_sql("extract/attach_remote.sql"))
        assert connection.table("remote.records").fetchall() == [(7,), (12,)]
        connection.execute(load_sql("extract/detach_remote.sql"))
        connection.execute(
            load_sql("extract/attach_remote_snapshot.sql"), {"version": version}
        )
        assert connection.table("remote.records").fetchall() == [(7,)]
        with pytest.raises(duckdb.InvalidInputException, match="read-only"):
            connection.execute(load_fixture_sql("ducklake/insert_record.sql"))
