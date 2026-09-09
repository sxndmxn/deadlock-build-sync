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
from tests.offline.sql_fixtures import load_fixture_sql


def test_expanded_matches_keep_original_splits_without_duplicates_or_test_data() -> (
    None
):
    cohort = Cohort(
        since=datetime.fromtimestamp(1000, UTC),
        as_of=datetime.fromtimestamp(2000, UTC),
    )
    with duckdb.connect() as connection:
        connection.execute(load_fixture_sql("rank_expansion/create_player_matches.sql"))
        _freeze_splits(connection, cohort)
        boundary = connection.execute(
            load_fixture_sql("select_split_boundaries.sql")
        ).fetchone()
        original = connection.execute(
            load_fixture_sql("select_match_folds_ordered.sql")
        ).fetchall()
        connection.execute(
            load_fixture_sql("rank_expansion/insert_expanded_matches.sql")
        )
        _freeze_splits(connection, cohort)
        assert (
            connection.execute(
                load_fixture_sql("select_split_boundaries.sql")
            ).fetchone()
            == boundary
        )
        assert (
            connection.execute(
                load_fixture_sql("rank_expansion/select_original_folds.sql")
            ).fetchall()
            == original
        )
        prepare_discovery_partitions(connection)
        partitions = connection.execute(
            load_fixture_sql("select_discovery_partitions.sql")
        ).fetchall()
        assert len(partitions) == len({match for match, _ in partitions}) == 16
        assert partitions[:8] == [
            (i, "discovery" if i <= 4 else "selection" if i == 5 else "validation")
            for i in range(8)
        ]
        assert partitions[8:] == [(i + 100, fold) for i, fold in partitions[:8]]
        assert connection.execute(
            load_fixture_sql("rank_expansion/select_match_sizes.sql")
        ).fetchall() == [(12,)]
        prepare_discovery_partitions(connection)
        assert (
            connection.execute(
                load_fixture_sql("select_discovery_partitions.sql")
            ).fetchall()
            == partitions
        )


def test_empty_starting_rank_range_uses_fixed_time_boundaries() -> None:
    with duckdb.connect() as connection:
        connection.execute(load_fixture_sql("rank_expansion/create_low_rank_match.sql"))
        _freeze_splits(
            connection,
            Cohort(
                since=datetime.fromtimestamp(1000, UTC),
                as_of=datetime.fromtimestamp(2000, UTC),
            ),
        )
        assert connection.execute(
            load_fixture_sql("select_split_boundaries.sql")
        ).fetchone() == (
            1450,
            1600,
            1800,
        )
        assert connection.execute(
            load_fixture_sql("select_match_folds.sql")
        ).fetchall() == [(1, "test")]


def test_missing_economy_and_enemy_rows_keep_complete_purchase_histories() -> None:
    with duckdb.connect() as connection:
        connection.execute(load_fixture_sql("missing_state/create_player_matches.sql"))
        connection.execute(load_fixture_sql("missing_state/create_partitions.sql"))
        connection.execute(load_fixture_sql("missing_state/create_compositions.sql"))
        connection.execute(
            load_fixture_sql("missing_state/create_player_snapshots.sql")
        )
        connection.execute(load_fixture_sql("missing_state/create_team_snapshots.sql"))
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
