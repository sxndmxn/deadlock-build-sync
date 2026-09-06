from dataclasses import replace

import duckdb
import pytest

from deadlock_build_sync.artifacts import ArtifactError
from deadlock_build_sync.build_evidence_timing import purchase_timing
from deadlock_build_sync.build_evidence_types import SequencePolicy, TierPolicyEvidence
from deadlock_build_sync.offline.production_timing import timing_payload
from tests.service_evidence_fixtures import build_evidence
from tests.service_fake_api import FakeApi, ability_rows, duration_points


def test_timing_counts_use_training_cohort_and_strict_adjacent_anchors() -> None:
    con = duckdb.connect()
    con.execute(
        "CREATE TABLE first_purchases (match_id BIGINT, player_slot INTEGER, hero_id INTEGER, item_id BIGINT, buy_time DOUBLE, fold VARCHAR)"
    )
    rows = [
        (key, 0, 12, item, time, fold)
        for key, fold in ((1, "train"), (2, "validation"), (3, "test"), (4, "train"))
        for item, time in ((10, 10), (20, 20), (30, 15), (40, 10))
    ]
    rows.extend([(1, 0, 12, 30, 50, "train"), (1, 0, 12, 50, 50, "train")])
    con.executemany("INSERT INTO first_purchases VALUES (?, ?, ?, ?, ?, ?)", rows)
    result = timing_payload(
        con,
        12,
        frozenset({(1, 0), (2, 0), (3, 0)}),
        (10, 20),
        {"item_ids_by_tier": {"1": [30, 40, 50, 60]}},
    )
    con.close()
    assert result == {
        "version": 1,
        "fold": "train",
        "core_path": [10, 20],
        "items": [
            {"item_id": 30, "buyers": 1, "counts_by_checkpoint": [0, 1, 0]},
            {"item_id": 40, "buyers": 1, "counts_by_checkpoint": [0, 0, 0]},
            {"item_id": 50, "buyers": 1, "counts_by_checkpoint": [0, 0, 1]},
            {"item_id": 60, "buyers": 0, "counts_by_checkpoint": [0, 0, 0]},
        ],
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"version": True},
        {"version": 2},
        {"core_path": [True, 2]},
        {"core_path": [2, 1]},
        {"fold": "test"},
        {"items": None},
        {"items": []},
        {"items": [None]},
        {"items": [{"item_id": True}]},
        {"items": [{"item_id": 100, "buyers": 35, "counts_by_checkpoint": [0, 36, 0]}]},
        {"items": [{"item_id": 100, "buyers": 34, "counts_by_checkpoint": [0, 30, 0]}]},
        {"items": [{"item_id": 100, "buyers": 35, "counts_by_checkpoint": [0, 30]}]},
        {"items": [{"item_id": 101, "buyers": 35, "counts_by_checkpoint": [0, 30, 0]}]},
        {
            "items": [
                {"item_id": 100, "buyers": 35, "counts_by_checkpoint": [0, 30, 0]}
            ]
            * 2
        },
    ],
)
def test_timing_extension_rejects_edited_or_incomplete_evidence(
    changes: dict[str, object],
) -> None:
    api = FakeApi(ability_rows=ability_rows(), duration_points=duration_points())
    item = replace(build_evidence(api).heroes[12].items[0], item_id=100)
    sequence = SequencePolicy((1, 2), (), 20, "deterministic_backoff", {})
    tiers = TierPolicyEvidence({1: (100,)})
    payload: dict[str, object] = {
        "version": 1,
        "fold": "train",
        "core_path": [1, 2],
        "items": [{"item_id": 100, "buyers": 35, "counts_by_checkpoint": [0, 30, 0]}],
    }
    assert purchase_timing(payload, sequence, tiers, (item,))[0].position == 1
    assert purchase_timing(None, sequence, tiers, (item,)) == ()
    with pytest.raises(ArtifactError):
        purchase_timing({**payload, **changes}, sequence, tiers, (item,))
