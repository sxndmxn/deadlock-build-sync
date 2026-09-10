"""Check strict purchase boundaries and state freshness at each checkpoint."""

import duckdb
import pytest

from deadlock_build_sync.offline.beam_support import core_state_statistics
from deadlock_build_sync.offline.discovery_data import (
    build_hero_discovery_data,
    load_landmark_rows,
    load_purchase_histories,
)
from deadlock_build_sync.value_validation import require_object_dict
from tests.offline.discovery_fixtures import make_item_graph
from tests.offline.sql_fixtures import load_fixture_sql


def test_thirty_minute_inventory_excludes_boundary_buys_and_later_sales() -> None:
    graph = make_item_graph()
    with duckdb.connect() as connection:
        connection.execute(
            load_fixture_sql("checkpoints/create_ownership_checkpoint.sql")
        )
        rows = load_landmark_rows(connection, 7, ownership_before_seconds=1800)
        histories = load_purchase_histories(
            connection, 7, ownership_before_seconds=1800
        )
        earlier = load_purchase_histories(connection, 7)
    assert rows[0] == (1, 0, "discovery", True, 18000, 0, 90, 1, [1, 2, 3, 4, 5, 6])
    assert {row[0] for row in rows} == {1, 3, 4, 5, 6, 7}
    assert {item for item, _bought, _sold in earlier[1, 0]} == {0, 4, 5}
    assert (4, 100, 1799) in histories[1, 0]
    assert (5, 100, 0) in histories[1, 0]
    data = build_hero_discovery_data(
        7, rows, histories, graph, ownership_before_seconds=1800
    )
    assert data.inventories[0] == (0, 1, 2, 5)
    assert data.ownership_before_seconds == 1800
    assert core_state_statistics(data, (0, 1, 2, 5), 1)["discovery"] == {
        "owners": 2,
        "wins": 2,
        "win_rate": 1.0,
        "lower_95": pytest.approx(0.34238, abs=0.0001),
        "upper_95": 1.0,
        "hero_matches": 2,
        "hero_win_rate": 1.0,
        "ownership_before_seconds": 1800,
    }


def test_checkpoint_keeps_missing_and_stale_states_distinct_from_even() -> None:
    with duckdb.connect() as connection:
        connection.execute(
            load_fixture_sql("checkpoints/create_ownership_checkpoint.sql")
        )
        earlier = load_landmark_rows(connection, 7)
        later = load_landmark_rows(connection, 7, ownership_before_seconds=1800)
    assert len(earlier) == 7
    assert all(row[4] == 10000 and row[7] == 1 for row in earlier)
    rows = {row[0]: row for row in later}
    assert rows[3][4] == 18000 and rows[3][7] == 1
    assert rows[4][4] is None and rows[4][7] is None
    assert rows[5][5] is None and rows[5][7] is None
    assert rows[6][5] is None and rows[6][7] is None
    assert rows[7][4] is None and rows[7][7] is None


def test_checkpoint_rejects_nonpositive_values() -> None:
    with pytest.raises(ValueError, match="checkpoint must be positive"):
        build_hero_discovery_data(
            7, [], {}, make_item_graph(), ownership_before_seconds=0
        )


def test_empty_checkpoint_reports_no_observed_win_rate() -> None:
    data = build_hero_discovery_data(
        7, [], {}, make_item_graph(), ownership_before_seconds=1800
    )
    for value in core_state_statistics(data, (1, 2, 3, 4), 1).values():
        evidence = require_object_dict(value)
        assert evidence["owners"] == 0
        assert evidence["win_rate"] is None
        assert evidence["hero_win_rate"] is None
