"""Expansion retains whole matches, fixed time partitions, and missing state."""

from datetime import UTC, datetime

import duckdb
import numpy as np

from deadlock_build_sync.offline.config import Cohort
from deadlock_build_sync.offline.discovery_data import (
    build_hero_discovery_data,
    load_landmark_rows,
    prepare_discovery_partitions,
)
from deadlock_build_sync.offline.extract import _freeze_splits
from tests.offline.discovery_fixtures import make_item_graph


def test_expanded_matches_keep_original_splits_without_duplicates_or_test_data() -> (
    None
):
    cohort = Cohort(
        since=datetime.fromtimestamp(1000, UTC),
        as_of=datetime.fromtimestamp(2000, UTC),
    )
    with duckdb.connect() as connection:
        connection.execute("""
            CREATE TABLE player_matches AS
            SELECT i AS match_id, s AS player_slot, 71 AS average_badge,
                   to_timestamp(1000+i*100) AS start_time
            FROM range(10) t(i) CROSS JOIN range(12) p(s)
        """)
        _freeze_splits(connection, cohort)
        boundary = connection.execute("SELECT * FROM split_boundaries").fetchone()
        original = connection.execute(
            "SELECT * FROM match_folds ORDER BY match_id"
        ).fetchall()
        connection.execute("""
            INSERT INTO player_matches
            SELECT match_id+100, player_slot, 61, start_time FROM player_matches
        """)
        _freeze_splits(connection, cohort)
        assert (
            connection.execute("SELECT * FROM split_boundaries").fetchone() == boundary
        )
        assert (
            connection.execute(
                "SELECT * FROM match_folds WHERE match_id<100 ORDER BY match_id"
            ).fetchall()
            == original
        )
        prepare_discovery_partitions(connection)
        partitions = connection.execute(
            "SELECT * FROM discovery_partitions ORDER BY match_id"
        ).fetchall()
        assert len(partitions) == len({match for match, _ in partitions}) == 16
        assert partitions[:8] == [
            (i, "discovery" if i <= 4 else "selection" if i == 5 else "validation")
            for i in range(8)
        ]
        assert partitions[8:] == [(i + 100, fold) for i, fold in partitions[:8]]
        assert connection.execute("""
            SELECT DISTINCT count(*) FROM player_matches p
            JOIN discovery_partitions d USING(match_id) GROUP BY match_id
        """).fetchall() == [(12,)]
        prepare_discovery_partitions(connection)
        assert (
            connection.execute(
                "SELECT * FROM discovery_partitions ORDER BY match_id"
            ).fetchall()
            == partitions
        )


def test_empty_starting_rank_range_uses_fixed_time_boundaries() -> None:
    with duckdb.connect() as connection:
        connection.execute("""
            CREATE TABLE player_matches AS SELECT 1 AS match_id,
                11 AS average_badge, to_timestamp(1900) AS start_time
        """)
        _freeze_splits(
            connection,
            Cohort(
                since=datetime.fromtimestamp(1000, UTC),
                as_of=datetime.fromtimestamp(2000, UTC),
            ),
        )
        assert connection.execute("SELECT * FROM split_boundaries").fetchone() == (
            1450,
            1600,
            1800,
        )
        assert connection.execute("SELECT * FROM match_folds").fetchall() == [
            (1, "test")
        ]


def test_missing_economy_and_enemy_rows_keep_complete_purchase_histories() -> None:
    with duckdb.connect() as connection:
        connection.execute("""
            CREATE TABLE player_matches AS SELECT i AS match_id,
                0 AS player_slot, 7 AS hero_id, 0 AS team_id, true AS won,
                71 AS average_badge, 1800 AS duration_s, to_timestamp(i) AS start_time
            FROM range(100) t(i)
        """)
        connection.execute("""
            CREATE TABLE discovery_partitions AS
            SELECT match_id, 'discovery' AS partition FROM player_matches
        """)
        connection.execute(
            "CREATE TABLE compositions(match_id INT, team_id INT, hero_ids INT[])"
        )
        connection.execute(
            "CREATE TABLE player_snapshots(match_id INT, player_slot INT, stat_time INT, net_worth INT)"
        )
        connection.execute(
            "CREATE TABLE team_snapshots(match_id INT, team_id INT, stat_time INT, team_net_worth INT, observed_players INT)"
        )
        rows = load_landmark_rows(connection, 7)
    assert len(rows) == 100
    data = build_hero_discovery_data(
        7,
        rows,
        {
            (match, 0): [(item, 100 + item, 0) for item in range(4)]
            for match in range(100)
        },
        make_item_graph(),
    )
    assert data.matrix.shape == (100, 4)
    assert data.matrix.all()
    assert np.isnan(data.wealth).all() and np.isnan(data.lead).all()
    assert np.isnan(data.relative_wealth).all()
    assert not data.enemies.any()
