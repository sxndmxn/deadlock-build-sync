from __future__ import annotations

import numpy as np
import pytest

from deadlock_build_sync.offline import discovery_branches as branches
from deadlock_build_sync.offline.contrast_features import build_contrast_feature_matrix
from tests.offline.test_discovery_branches import decisions, nominee
from tests.purchase_guidance_fixtures import make_purchase_guidance


def test_comparison_cohort_keeps_condition_specific_columns() -> None:
    _, graph = make_purchase_guidance()
    base = decisions()[0]
    rows = [
        {**base, "match_id": 1, "enemy_heroes": [42]},
        {**base, "match_id": 2, "enemy_heroes": [43], "context_custom": 1},
    ]
    candidate: dict[str, object] = {
        "item_id": 7,
        "after_step": 2,
        "comparator_item_id": 2,
        "condition": "enemy_hero",
        "value": 42,
    }
    cache: dict[tuple[int, int, int], branches.ChoiceCohort] = {}
    first = branches.build_comparison_frame(rows, nominee(), candidate, graph, cache)
    second = branches.build_comparison_frame(
        rows, nominee(), {**candidate, "value": 43}, graph, cache
    )
    assert first["match_id"].to_list() == [1]
    assert "context_custom" not in first.columns
    assert second["context_custom"].to_list() == [1]
    assert cache[7, 2, 2].frame is None


def test_substitution_inventory_cache_retains_observation_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, graph = make_purchase_guidance()
    rows: list[dict[str, object]] = [
        {"owned_before": inventory} for inventory in ([1], [2], [1], [2], [3])
    ]
    cohort = branches.ChoiceCohort.from_observations([
        branches.ChoiceObservation(row, {("enemy_hero", 42)}) for row in rows
    ])
    calls = []

    def check(row: dict[str, object], *_args: object) -> bool:
        calls.append(row["owned_before"])
        return row["owned_before"] != [2]

    monkeypatch.setattr(branches, "is_substitution_legal", check)
    selected = cohort.select_indices(
        {"condition": "enemy_hero", "value": 42, "substitution": {}}, graph
    )
    assert selected == [0, 2, 4]
    assert calls == [[1], [2], [3]]


def test_shared_features_keep_first_observation_indices() -> None:
    _, graph = make_purchase_guidance()
    base = decisions()[0]
    rows = [
        {**base, "match_id": match, "enemy_heroes": [42], "context_custom": value}
        for match, value in ((1, 10), (1, 20), (2, 30))
    ]
    candidate: dict[str, object] = {
        "item_id": 7,
        "after_step": 2,
        "comparator_item_id": 2,
        "condition": "enemy_hero",
        "value": 42,
    }
    frame, cohort, indices = branches._select_comparison_rows(
        rows, nominee(), candidate, graph, {}
    )
    assert frame["context_custom"].to_list() == [10, 30]
    assert cohort is not None
    assert cohort.observations == []
    table = cohort.feature_table
    actual = table.select(indices)
    expected = build_contrast_feature_matrix(frame)
    assert actual.tobytes() == expected.tobytes()
    assert cohort.feature_table is table
    actual[:] = 9
    np.testing.assert_array_equal(table.select(indices), expected)


def test_sparse_observations_keep_inventory_fallback_and_require_matching_columns() -> (
    None
):
    cohort = branches.ChoiceCohort.from_observations([
        branches.ChoiceObservation({"owned_before": [1]}, set()),
        branches.ChoiceObservation({"owned_before": [1], "context_custom": 1}, set()),
    ])
    assert cohort.inventories == ((1,), (1,))
    assert cohort.inventories[0] is cohort.inventories[1]
    with pytest.raises(ValueError, match="consistent observation columns"):
        _ = cohort.feature_table
    empty = branches.ChoiceCohort.from_observations([
        branches.ChoiceObservation({"match_id": 1}, set())
    ])
    assert empty.inventories == ((),)
