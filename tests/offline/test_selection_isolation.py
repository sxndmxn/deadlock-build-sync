from __future__ import annotations

import duckdb

from deadlock_build_sync.mechanics import ItemGraph
from deadlock_build_sync.offline.production_policy import _item_payload
from deadlock_build_sync.offline.production_sources import _path_item_metrics
from deadlock_build_sync.offline.production_storage import _core_alternative_candidates
from tests.mechanics_fixtures import item


def test_test_period_cannot_change_imbues_or_alternative_shortlist() -> None:
    con = duckdb.connect()
    con.execute("""
        CREATE TABLE first_purchases AS SELECT
            i AS match_id, 0 AS player_slot, 7 AS hero_id, j AS item_id,
            'Item' AS item_name, 1 AS tier, 500 AS cost, 'weapon' AS slot,
            false AS active,
            CASE WHEN i<=25 THEN 'train' WHEN i<=50 THEN 'validation'
                 ELSE 'test' END AS fold,
            i%2=0 AS won, 600+j AS buy_time, 10000+j AS own_net_worth_at_buy,
            CASE WHEN i<=15 OR i BETWEEN 26 AND 40 THEN 40 ELSE 41 END
                AS imbued_ability_id
        FROM range(1,71) actors(i) CROSS JOIN range(1,8) items(j)
        WHERE j NOT IN (2,3,4) OR (i <= 52-j) OR (j=4 AND i>50)
    """)
    con.execute("CREATE TABLE purchases AS SELECT * FROM first_purchases")
    members = frozenset((match_id, 0) for match_id in range(1, 71))
    graph = ItemGraph.from_assets([item(i, f"item_{i}") for i in range(1, 8)])
    try:
        before = _path_item_metrics(con, members)
        con.execute("""
            UPDATE first_purchases SET imbued_ability_id=40, won=true,
                own_net_worth_at_buy=50000 WHERE fold='test'
        """)
        con.execute("DELETE FROM first_purchases WHERE fold='test' AND item_id=4")
        after = _path_item_metrics(con, members)
    finally:
        con.close()
    outputs = []
    for frame in (before, after):
        metrics = {int(row["item_id"]): row for row in frame.iter_rows(named=True)}
        payload = _item_payload(
            metrics[1],
            {40: {"name": "First"}, 41: {"name": "Second"}},
            {"train": 25, "validation": 25, "test": 20},
        )
        candidates = _core_alternative_candidates(
            metrics,
            (1, 5, 6, 7),
            {1, 5, 6, 7},
            5,
            metrics[5],
            graph,
            {},
        )
        outputs.append((
            payload["imbue_target_ability_id"],
            [row["item_id"] for row in candidates],
        ))
    assert outputs == [(40, [2, 3]), (40, [2, 3])]
    assert before["raw_outcome_rate"].to_list() != after["raw_outcome_rate"].to_list()
