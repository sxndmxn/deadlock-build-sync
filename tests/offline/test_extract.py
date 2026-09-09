from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

import duckdb
import pytest

from deadlock_build_sync.offline import extract
from deadlock_build_sync.offline.config import Cohort, parse_timestamp
from deadlock_build_sync.offline.extract import (
    _build_cohort_parameters,
    _execute_remote_query,
)
from deadlock_build_sync.offline.sql_resources import load_sql
from tests.offline.sql_fixtures import load_fixture_sql


@dataclass(frozen=True)
class _Match:
    match_id: int
    players: int = 12
    start_time: str = "2026-08-16 23:00:00+00"
    duration_s: int = 1_800
    eligible: bool = True
    match_mode: str = "Ranked"


@pytest.mark.parametrize(
    "timestamp",
    ["2026-08-17T00:00:00", "2026-08-17T00:00:00Z", "2026-08-16T17:00:00-07:00"],
)
def test_frozen_cohort_metadata_preserves_utc_boundaries(timestamp: str) -> None:
    assert parse_timestamp(None) is None
    cohort = Cohort(
        since=datetime(2026, 8, 16, tzinfo=UTC), as_of=parse_timestamp(timestamp)
    )
    assert cohort.as_dict() == {
        "minimum_badge": 71,
        "maximum_badge": 115,
        "since": "2026-08-16T00:00:00+00:00",
        "as_of": "2026-08-17T00:00:00+00:00",
        "match_mode": "Ranked",
        "game_mode": "Normal",
    }


def _insert_match(
    connection: duckdb.DuckDBPyConnection,
    match: _Match,
) -> None:
    rows = [
        (
            match.match_id,
            slot,
            "Team0" if slot < 6 else "Team1",
            "Win" if slot < 6 else "Loss",
            match.eligible,
            match.match_mode,
            "Normal",
            match.start_time,
            match.duration_s,
            90,
        )
        for slot in range(match.players)
    ]
    connection.executemany(load_fixture_sql("extract/insert_match_player.sql"), rows)


def test_match_admission_requires_complete_eligible_twelve_player_match() -> None:
    connection = duckdb.connect()
    connection.execute(load_fixture_sql("extract/create_match_player.sql"))
    _insert_match(connection, _Match(1))
    _insert_match(connection, _Match(2, players=6))
    _insert_match(connection, _Match(3, players=11))
    _insert_match(connection, _Match(4, eligible=False))
    _insert_match(
        connection,
        _Match(
            5,
            start_time="2026-08-16 23:50:00+00",
            duration_s=1_200,
        ),
    )
    cohort = Cohort(
        since=datetime(2026, 8, 16, tzinfo=UTC),
        as_of=datetime(2026, 8, 17, tzinfo=UTC),
    )

    connection.execute(
        load_sql("extract/create_eligible_matches.sql"),
        _build_cohort_parameters(cohort),
    )
    admitted = connection.table("eligible_matches").fetchall()

    assert admitted == [(1,)]


def test_remote_query_retries_a_shard_that_is_still_publishing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FlakyConnection:
        calls = 0

        def __init__(self) -> None:
            self.parameters: list[object] = []

        def execute(self, _query: str, parameters: object = None) -> "FlakyConnection":
            self.calls += 1
            self.parameters.append(parameters)
            if self.calls == 1:
                raise duckdb.InvalidInputException(
                    "No magic bytes found at end of file 'snapshot.parquet'"
                )
            return self

    connection = FlakyConnection()
    monkeypatch.setattr(extract.time, "sleep", lambda _delay: None)

    result = _execute_remote_query(
        cast("duckdb.DuckDBPyConnection", connection),
        load_fixture_sql("select_value.sql"),
        {"value": 1},
    )

    assert result is connection
    assert connection.calls == 2
    assert connection.parameters == [{"value": 1}, {"value": 1}]


def test_match_admission_binds_mode_text_without_sql_interpolation() -> None:
    mode = "Ranked'; DROP TABLE remote.main.match_player; --"
    cohort = Cohort(
        since=datetime(2026, 8, 16, tzinfo=UTC),
        as_of=datetime(2026, 8, 17, tzinfo=UTC),
        match_mode=mode,
    )
    with duckdb.connect() as connection:
        connection.execute(load_fixture_sql("extract/create_match_player.sql"))
        _insert_match(connection, _Match(1, match_mode=mode))
        _insert_match(connection, _Match(2))
        connection.execute(
            load_sql("extract/create_eligible_matches.sql"),
            _build_cohort_parameters(cohort),
        )
        assert connection.table("eligible_matches").fetchall() == [(1,)]
        assert len(connection.table("remote.main.match_player").fetchall()) == 24
