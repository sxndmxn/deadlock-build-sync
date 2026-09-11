"""Reject incomplete matches, invalid team states, and purchases after completion."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import duckdb
import pytest

from deadlock_build_sync.offline.config import Cohort
from deadlock_build_sync.offline.extract import _build_cohort_parameters
from deadlock_build_sync.offline.sql_resources import load_sql
from tests.offline.sql_fixtures import load_fixture_sql

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture
def source_connection() -> Iterator[duckdb.DuckDBPyConnection]:
    with duckdb.connect() as connection:
        connection.execute(load_fixture_sql("extract/attach_memory.sql"))
        connection.execute(load_fixture_sql("extract/create_source_tables.sql"))
        yield connection


def _admit_matches(connection: duckdb.DuckDBPyConnection) -> None:
    cohort = Cohort(
        since=datetime(2026, 8, 1, tzinfo=UTC),
        as_of=datetime(2026, 8, 2, tzinfo=UTC),
    )
    connection.execute(
        load_sql("extract/create_eligible_matches.sql"),
        _build_cohort_parameters(cohort),
    )


@pytest.mark.parametrize("eligible", [None, False, True])
def test_admission_requires_explicit_reward_eligibility(
    source_connection: duckdb.DuckDBPyConnection, *, eligible: bool | None
) -> None:
    source_connection.execute(
        load_fixture_sql("extract/set_reward_eligibility.sql"), [eligible]
    )
    _admit_matches(source_connection)
    admitted = {
        row[0] for row in source_connection.table("eligible_matches").fetchall()
    }
    assert (1 in admitted) is (eligible is True)
    assert admitted - {1} == set(range(2, 31))


@pytest.mark.parametrize("badge", [None, 50, 90, 120])
def test_admission_checks_all_source_players_before_extraction(
    source_connection: duckdb.DuckDBPyConnection, badge: int | None
) -> None:
    source_connection.execute(
        load_fixture_sql("extract/insert_extra_player.sql"), {"minimum_badge": badge}
    )
    _admit_matches(source_connection)
    source_connection.execute(load_sql("extract/create_player_matches.sql"))
    admitted = {
        row[0] for row in source_connection.table("eligible_matches").fetchall()
    }
    extracted = source_connection.table("player_matches").fetchall()
    assert admitted == set(range(2, 31))
    assert len(extracted) == 29 * 12
    assert all(row[0] != 1 for row in extracted)


@pytest.mark.parametrize(
    ("times", "wealth", "observed_players"),
    [
        ([99, 599, 899, 1199], [None, 6000, 9000, 10000], 5),
        ([99, 599, 899, 1199], [1000, 6000, 9000], 5),
        ([99, 599, 899], [1000, 6000, 9000, 10000], 5),
        ([99, 99, 599, 899, 1199], [1000, 1000, 6000, 9000, 10000], 6),
    ],
    ids=["null-wealth", "short-wealth-array", "short-time-array", "duplicate-time"],
)
def test_incomplete_team_snapshot_retains_unknown_wealth(
    source_connection: duckdb.DuckDBPyConnection,
    times: list[int],
    wealth: list[int | None],
    observed_players: int,
) -> None:
    source_connection.execute(
        load_fixture_sql("extract/set_player_snapshots.sql"), [times, wealth]
    )
    _admit_matches(source_connection)
    source_connection.execute(load_sql("extract/create_team_snapshots.sql"))
    snapshots = {
        (match, team, time): (value, players)
        for match, team, time, value, players in source_connection.table(
            "team_snapshots"
        ).fetchall()
    }
    assert snapshots[1, 0, 99] == (None, observed_players)
    assert snapshots[2, 0, 99] == (6015, 6)


@pytest.mark.parametrize(("duration", "purchases"), [(99, 0), (100, 12), (101, 12)])
def test_extraction_rejects_purchases_after_match_completion(
    source_connection: duckdb.DuckDBPyConnection, duration: int, purchases: int
) -> None:
    source_connection.execute(
        load_fixture_sql("extract/set_match_duration.sql"), [duration]
    )
    _admit_matches(source_connection)
    source_connection.execute(load_sql("extract/create_item_assets.sql"))
    source_connection.execute(
        load_sql("extract/insert_item_assets.sql"),
        [10, "Item", "item_10", 1, 800, "weapon", False, True, "[]"],
    )
    source_connection.execute(load_sql("extract/create_purchases.sql"))
    rows = source_connection.table("purchases").fetchall()
    assert sum(row[0] == 1 for row in rows) == purchases
