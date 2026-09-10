from dataclasses import replace

import pytest

from deadlock_build_sync.artifacts import ArtifactError
from deadlock_build_sync.build_evidence_timing import parse_purchase_timing
from deadlock_build_sync.build_evidence_types import SequencePolicy, TierPolicyEvidence
from deadlock_build_sync.offline.production_timing import _count_purchase_intervals
from tests.service_evidence_fixtures import make_service_build_evidence
from tests.service_fake_api import FakeApi, make_ability_rows, make_duration_statistics


def test_timing_counts_require_strict_adjacent_anchors() -> None:
    assert _count_purchase_intervals(
        [30, 40, 50, 60], (10, 20), {(1, 0): {10: 10, 20: 20, 30: 15, 40: 10, 50: 50}}
    ) == [
        {"item_id": 30, "buyers": 1, "counts_by_checkpoint": [0, 1, 0]},
        {"item_id": 40, "buyers": 1, "counts_by_checkpoint": [0, 0, 0]},
        {"item_id": 50, "buyers": 1, "counts_by_checkpoint": [0, 0, 1]},
        {"item_id": 60, "buyers": 0, "counts_by_checkpoint": [0, 0, 0]},
    ]


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
    api = FakeApi(
        ability_rows=make_ability_rows(), duration_points=make_duration_statistics()
    )
    item = replace(make_service_build_evidence(api).heroes[12].items[0], item_id=100)
    sequence = SequencePolicy((1, 2), (), 20, "deterministic_backoff", {})
    tiers = TierPolicyEvidence({1: (100,)})
    payload: dict[str, object] = {
        "version": 1,
        "fold": "train",
        "core_path": [1, 2],
        "items": [{"item_id": 100, "buyers": 35, "counts_by_checkpoint": [0, 30, 0]}],
    }
    assert parse_purchase_timing(payload, sequence, tiers, (item,))[0].position == 1
    assert parse_purchase_timing(None, sequence, tiers, (item,)) == ()
    with pytest.raises(ArtifactError):
        parse_purchase_timing({**payload, **changes}, sequence, tiers, (item,))
