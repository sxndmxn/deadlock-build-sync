from __future__ import annotations

import duckdb

from deadlock_build_sync.offline.production_items import _build_item_evidence_payload
from deadlock_build_sync.offline.production_sources import _query_path_item_metrics
from tests.offline.sql_fixtures import load_fixture_sql


def test_test_period_cannot_change_imbue_selection() -> None:
    connection = duckdb.connect()
    connection.execute(load_fixture_sql("selection/create_first_purchases.sql"))
    connection.execute(load_fixture_sql("selection/create_purchases.sql"))
    members = frozenset((match_id, 0) for match_id in range(1, 71))
    try:
        before = _query_path_item_metrics(connection, members)
        connection.execute(load_fixture_sql("selection/change_test_observations.sql"))
        connection.execute(load_fixture_sql("selection/remove_test_item.sql"))
        after = _query_path_item_metrics(connection, members)
    finally:
        connection.close()
    outputs = []
    for frame in (before, after):
        metrics = {int(row["item_id"]): row for row in frame.iter_rows(named=True)}
        payload = _build_item_evidence_payload(
            metrics[1],
            {40: {"name": "First"}, 41: {"name": "Second"}},
            {"train": 25, "validation": 25, "test": 20},
        )
        outputs.append(payload["imbue_target_ability_id"])
    assert outputs == [40, 40]
    assert before["raw_outcome_rate"].to_list() != after["raw_outcome_rate"].to_list()
