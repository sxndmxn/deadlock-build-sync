from __future__ import annotations

import duckdb
import numpy as np
import pytest

from deadlock_build_sync.offline.discovery_checkpoints import (
    load_purchase_event_histories,
)
from deadlock_build_sync.offline.purchase_event_table import PurchaseEventTable
from tests.offline.sql_fixtures import load_fixture_sql


def test_purchase_table_preserves_actor_event_order_and_repeated_purchases() -> None:
    records = np.array(
        [
            [4, 1, 0, 9000000001, 100, 300],
            [4, 1, 0, 2, 100, 0],
            [4, 1, 0, 2, 100, 0],
            [4, 7, 1, 3, 120, 0],
            [9, 1, 0, 4, 130, 500],
        ],
        dtype=np.int64,
    )
    table = PurchaseEventTable(records[:, 0], records[:, 1], records[:, 2:])
    for match in (0, 4, 5, 9, 10):
        expected: dict[int, list[tuple[int, ...]]] = {}
        for recorded, slot, *event in records.tolist():
            if recorded == match:
                expected.setdefault(slot, []).append(tuple(event))
        assert table.for_match(match) == expected
    empty = PurchaseEventTable(np.empty(0), np.empty(0), np.empty((0, 4)))
    assert empty.for_match(1) == {}


def test_selected_histories_do_not_change_shared_purchase_arrays() -> None:
    table = PurchaseEventTable(np.array([1]), np.array([2]), np.array([[0, 7, 100, 0]]))
    first = table.for_match(1)
    first[2].clear()
    assert table.for_match(1) == {2: [(0, 7, 100, 0)]}


def test_unsigned_match_search_preserves_integer_precision() -> None:
    matches = np.array([2**63, 2**63 + 1, 2**63 + 2], dtype=np.uint64)
    table = PurchaseEventTable(
        matches, np.array([1, 2, 3]), np.array([[0, 7, 100, 0]] * 3)
    )
    for index, match in enumerate(matches):
        assert table.for_match(int(match)) == {index + 1: [(0, 7, 100, 0)]}
    assert table.for_match(-1) == {}
    assert table.for_match(2**64) == {}


def test_database_history_preserves_missing_sale_times_and_rejects_missing_items() -> (
    None
):
    with duckdb.connect() as connection:
        connection.execute(load_fixture_sql("checkpoints/create_single_partition.sql"))
        connection.execute(load_fixture_sql("checkpoints/create_hero_appearance.sql"))
        connection.execute(
            load_fixture_sql("checkpoints/create_large_item_purchases.sql")
        )
        connection.execute(load_fixture_sql("checkpoints/insert_missing_sale.sql"))
        assert load_purchase_event_histories(connection, 12).for_match(1) == {
            0: [(0, 9000000001, 100, 0)]
        }
        connection.execute(load_fixture_sql("checkpoints/remove_item_identifiers.sql"))
        with pytest.raises(ValueError, match="incomplete"):
            load_purchase_event_histories(connection, 12)
