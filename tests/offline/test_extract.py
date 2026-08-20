from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

import duckdb
import pytest

from deadlock_build_sync.offline import extract
from deadlock_build_sync.offline.config import Cohort
from deadlock_build_sync.offline.extract import (
    _eligible_matches_query,
    _execute_remote_query,
)


@dataclass(frozen=True)
class _Match:
    match_id: int
    players: int = 12
    start_time: str = "2026-08-16 23:00:00+00"
    duration_s: int = 1_800
    eligible: bool = True


def _insert_match(
    con: duckdb.DuckDBPyConnection,
    match: _Match,
) -> None:
    rows = [
        (
            match.match_id,
            slot,
            "Team0" if slot < 6 else "Team1",
            "Win" if slot < 6 else "Loss",
            match.eligible,
            "Ranked",
            "Normal",
            match.start_time,
            match.duration_s,
            90,
        )
        for slot in range(match.players)
    ]
    con.executemany(
        "INSERT INTO match_player VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows
    )


def test_match_admission_requires_complete_eligible_twelve_player_match() -> None:
    con = duckdb.connect()
    con.execute(
        """
        CREATE TABLE match_player (
            match_id INTEGER,
            player_slot INTEGER,
            team VARCHAR,
            player_match_outcome VARCHAR,
            rewards_eligible BOOLEAN,
            match_mode VARCHAR,
            game_mode VARCHAR,
            start_time TIMESTAMPTZ,
            duration_s INTEGER,
            average_badge INTEGER
        )
        """
    )
    _insert_match(con, _Match(1))
    _insert_match(con, _Match(2, players=6))
    _insert_match(con, _Match(3, players=11))
    _insert_match(con, _Match(4, eligible=False))
    _insert_match(
        con,
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

    admitted = con.execute(
        _eligible_matches_query(cohort, source="match_player")
    ).fetchall()

    assert admitted == [(1,)]


def test_remote_query_retries_a_shard_that_is_still_publishing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FlakyConnection:
        calls = 0

        def execute(self, _query: str) -> "FlakyConnection":
            self.calls += 1
            if self.calls == 1:
                raise duckdb.InvalidInputException(
                    "No magic bytes found at end of file 'snapshot.parquet'"
                )
            return self

    connection = FlakyConnection()
    monkeypatch.setattr(extract.time, "sleep", lambda _delay: None)

    result = _execute_remote_query(
        cast("duckdb.DuckDBPyConnection", connection),
        "SELECT 1",
    )

    assert result is connection
    assert connection.calls == 2
