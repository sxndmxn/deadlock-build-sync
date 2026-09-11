"""Keep research queries in SQLFluff coverage and the data fingerprint."""

from __future__ import annotations

import ast
import json
import shutil
from pathlib import Path

import duckdb
import polars as pl
import pytest

from tests.offline.sql_fixtures import load_fixture_sql
from tools.purchase_search import dataset


@pytest.mark.parametrize("directory", ["src", "tools", "tests"])
def test_database_statements_use_sql_resources(directory: str) -> None:
    root = Path(__file__).parents[1] / directory
    inline_queries = []
    for path in root.rglob("*.py"):
        inline_queries.extend(
            (str(path.relative_to(root)), node.lineno)
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"execute", "executemany", "sql"}
                and node.args
                and isinstance(node.args[0], (ast.Constant, ast.JoinedStr))
            )
        )
    assert inline_queries == []


def test_research_statistics_keep_selected_match_counts() -> None:
    with duckdb.connect() as connection:
        connection.register(
            "player_matches",
            pl.DataFrame({
                "match_id": [1, 1, 2, 3],
                "hero_id": [6, 7, 6, 6],
                "won": [True, False, False, False],
            }),
        )
        connection.register("experiment_matches", pl.DataFrame({"match_id": [1, 3]}))
        connection.register(
            "match_folds",
            pl.DataFrame({
                "match_id": [1, 2, 3, 4],
                "fold": ["train", "train", "train", "test"],
            }),
        )
        assert connection.execute(
            dataset.read_sql("select_hero_counts.sql")
        ).fetchall() == [(6, 2, 1), (7, 1, 0)]
        assert connection.execute(
            dataset.read_sql("count_eligible_matches.sql")
        ).fetchone() == (2,)
        for partition in ("train", "test", "validation"):
            assert connection.execute(
                dataset.read_sql("count_excluded_matches.sql"),
                {"partition": partition},
            ).fetchone() == (0 if partition == "validation" else 1,)


@pytest.mark.parametrize(
    "name",
    [
        "select_hero_counts.sql",
        "count_eligible_matches.sql",
        "count_excluded_matches.sql",
    ],
)
def test_statistics_sql_changes_invalidate_the_data_fingerprint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    source = tmp_path / "source"
    (source / "raw").mkdir(parents=True)
    (source / "manifest.json").write_text(
        json.dumps({
            "cohort": {"as_of": "2026-09-11T00:00:00Z"},
            "sources": {"source_sha256": {"items.json": "a" * 64}},
            "extraction": {"source_snapshot_version": 7},
        }),
        encoding="utf-8",
    )
    (source / "raw/patches.json").write_text(
        json.dumps([{"pub_date": "2026-09-01T00:00:00Z"}]), encoding="utf-8"
    )
    sql_directory = shutil.copytree(dataset.SQL_DIRECTORY, tmp_path / "sql")
    monkeypatch.setattr(dataset, "SQL_DIRECTORY", sql_directory)
    previous = dataset.source_identity(source, 100, 120)
    query = sql_directory / name
    query.write_text(query.read_text(encoding="utf-8") + "\n-- Changed query.\n")
    current = dataset.source_identity(source, 100, 120)
    assert current["fingerprint"] != previous["fingerprint"]


@pytest.mark.parametrize(("duration", "rows"), [(None, 0), (95, 0), (100, 1)])
def test_research_observations_reject_purchases_after_match_completion(
    duration: int | None, rows: int
) -> None:
    with duckdb.connect() as connection:
        connection.execute(load_fixture_sql("beam/create_purchase_observations.sql"))
        connection.execute(load_fixture_sql("search/create_purchase_partitions.sql"))
        connection.execute(load_fixture_sql("beam/set_match_duration.sql"), [duration])
        connection.execute(
            dataset.read_sql("create_observations.sql"),
            {"partition": "train", "freshness": 120},
        )
        assert len(connection.table("experiment_observations").fetchall()) == rows
