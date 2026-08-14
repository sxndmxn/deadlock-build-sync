import polars as pl
import pytest

from deadlock_build_sync.offline.analysis import (
    _effective_property_value,
    _interval_overlap_ratio,
    _with_matchup_residual,
)


def test_matchup_residual_subtracts_hero_enemy_main_effect() -> None:
    item_cells = pl.DataFrame({
        "scope": ["same_lane", "same_lane"],
        "hero_id": [1, 1],
        "item_id": [10, 11],
        "enemy_hero_id": [2, 2],
        "shrunk_item_delta": [0.08, -0.02],
    })
    hero_effects = pl.DataFrame({
        "scope": ["same_lane"],
        "hero_id": [1],
        "enemy_hero_id": [2],
        "shrunk_hero_delta": [0.05],
    })

    adjusted = _with_matchup_residual(
        item_cells,
        hero_effects,
        join_keys=["scope", "hero_id", "enemy_hero_id"],
        item_delta="shrunk_item_delta",
        hero_delta="shrunk_hero_delta",
        output="item_residual",
    )

    assert adjusted["item_residual"].to_list() == pytest.approx([0.03, -0.07])


def test_effective_property_value_rejects_engine_sentinels() -> None:
    for value in (None, "", "0", 0, "-1.0", -2, False):
        assert not _effective_property_value({"value": value})
    for value in ("0.5", 1, "12m", True):
        assert _effective_property_value({"value": value})


def test_interval_overlap_ratio_handles_overlap_disjoint_and_points() -> None:
    assert _interval_overlap_ratio(1, 5, 3, 7) == pytest.approx(2 / 6)
    assert _interval_overlap_ratio(1, 2, 3, 4) == 0
    assert _interval_overlap_ratio(2, 2, 2, 2) == 1
    assert _interval_overlap_ratio(None, 2, 1, 2) is None
