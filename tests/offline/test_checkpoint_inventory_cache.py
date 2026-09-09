from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING

import duckdb
import numpy as np

from deadlock_build_sync.offline import discovery_checkpoints as checkpoints
from deadlock_build_sync.offline.purchase_event_table import PurchaseEventTable
from tests.purchase_guidance_fixtures import make_purchase_guidance

if TYPE_CHECKING:
    import pytest


def test_enemy_inventory_cache_separates_matches_teams_and_observation_times(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, graph = make_purchase_guidance()
    rows: list[dict[str, object]] = [
        {
            "match_id": match,
            "player_slot": team,
            "team_id": team,
            "buy_time": 500,
            "enemy_observed": observed,
            "enemy_heroes": [42],
            "partition": "discovery",
            "own_net_worth_at_buy": 1000,
        }
        for match, team, observed in (
            (1, 0, 300),
            (1, 0, 300),
            (1, 0, 400),
            (1, 1, 300),
            (2, 0, 300),
            (2, 0, 100),
        )
    ]
    histories = {
        (1, 0): [(0, 1, 100, 0)],
        (1, 1): [(1, 7, 100, 350), (1, 8, 400, 0)],
        (2, 0): [(0, 3, 100, 0)],
        (2, 1): [(1, 9, 100, 0)],
    }
    records = np.array([
        (match, slot, *event)
        for (match, slot), events in histories.items()
        for event in events
    ])
    table = PurchaseEventTable(records[:, 0], records[:, 1], records[:, 2:])
    monkeypatch.setattr(
        checkpoints, "load_decision_rows", lambda *_args: deepcopy(rows)
    )
    monkeypatch.setattr(
        checkpoints, "load_purchase_event_histories", lambda *_args: table
    )
    with duckdb.connect() as connection:
        actual = checkpoints.load_checkpoint_rows(connection, 12, graph)
    assert [row["enemy_items"] for row in actual] == [[7], [7], [8], [1], [9], []]
    assert actual[0]["enemy_items"] is not actual[1]["enemy_items"]
    assert actual[-1]["enemy_heroes"] == []
