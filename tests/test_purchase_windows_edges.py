from __future__ import annotations

import math

from deadlock_build_sync import purchase_windows
from deadlock_build_sync.purchase_types import (
    GroupedPurchaseBucket,
    PurchaseBucketRow,
)


def _row(bucket: int | None, matches: int, wins: int) -> PurchaseBucketRow:
    return PurchaseBucketRow(bucket, matches, wins)


def _group(start: int, matches: int, wins: int) -> GroupedPurchaseBucket:
    return GroupedPurchaseBucket(start, start + 1_000, matches, wins, 0.0, 0.0)


def test_wilson_and_grouping_handle_empty_and_invalid_rows() -> None:
    assert purchase_windows.wilson_score_interval(0, 0) == (0.0, 0.0)
    rows = [_row(None, 10, 5), _row(1_000, 0, 0), _row(1_200, 10, 6)]

    groups = purchase_windows.group_purchase_buckets(rows, 1_000)

    assert len(groups) == 1
    assert groups[0].bucket_start == 1_000
    assert groups[0].observed_outcome_rate == 0.6
    assert purchase_windows.compute_average_bucket_matches([], 1_000) == 0.0


def test_adaptive_increment_handles_empty_low_and_high_volume() -> None:
    rows = [_row(1_000, 10, 5), _row(2_000, 10, 5)]
    assert purchase_windows.choose_adaptive_bucket_increment(rows, 0, ()) == 1_000
    assert (
        purchase_windows.choose_adaptive_bucket_increment(rows, 20, (1_000,)) == 1_000
    )
    assert (
        purchase_windows.choose_adaptive_bucket_increment(rows, 10_000, (100, 200))
        == 200
    )


def test_weighted_median_and_horizons_skip_empty_series() -> None:
    assert purchase_windows._weighted_median_purchase_net_worth([]) is None
    assert (
        purchase_windows._weighted_median_purchase_net_worth([
            _row(None, 10, 5),
            _row(2_000, 2, 1),
            _row(1_000, 8, 4),
        ])
        == 1_500
    )
    assert purchase_windows.calculate_tier_horizons([
        (1, []),
        (2, [_row(1_000, 10, 5)]),
        (2, [_row(2_000, 2, 1)]),
    ]) == {2: 3_000}


def test_aggregate_and_window_selection_handle_zero_and_ineligible_groups() -> None:
    zero = purchase_windows._aggregate_window([_group(0, 0, 0)], 0, 0)
    assert zero.observed_outcome_rate == 0.0

    groups = [_group(0, 20, 10), _group(1_000, 20, 10)]
    assert purchase_windows.select_purchase_windows(groups, -1) == []
    selected = purchase_windows.select_purchase_windows(
        groups,
        math.inf,
        total_bucket_matches=40,
    )
    assert len(selected) == 1
    assert selected[0].matches == 40


def test_shopable_assets_enforces_every_asset_gate() -> None:
    assets: list[dict[str, object]] = [
        {"id": 1, "item_tier": 1, "shopable": True, "shop_image_webp": "image"},
        {"id": 2, "item_tier": 1, "shopable": False, "shop_image_webp": "image"},
        {
            "id": 3,
            "item_tier": 1,
            "shopable": True,
            "disabled": True,
            "shop_image_webp": "image",
        },
        {"id": 4, "item_tier": 1, "shopable": True},
        {"id": "5", "item_tier": 1, "shopable": True, "shop_image_webp": "image"},
        {"id": 6, "item_tier": "1", "shopable": True, "shop_image_webp": "image"},
        {"id": 7, "item_tier": 5, "shopable": True, "shop_image_webp": "image"},
    ]
    assert set(purchase_windows._shopable_assets(assets)) == {1}


def test_bucket_and_overall_rows_filter_unknown_items_and_bad_values() -> None:
    assets: dict[int, dict[str, object]] = {1: {"id": 1}}
    rows: list[dict[str, object]] = [
        {"item_id": "1", "bucket": 1_000},
        {"item_id": 2, "bucket": 1_000},
        {"item_id": 1, "bucket": "bad", "matches": 3, "wins": 2},
    ]
    buckets = purchase_windows._bucket_rows(rows, assets)
    assert buckets[1] == [PurchaseBucketRow(None, 3, 2)]

    assert purchase_windows._eligible_item_stats(
        [
            {"item_id": "1", "matches": 2},
            {"item_id": 2, "matches": 2},
            {"item_id": 1, "matches": 0},
            {"item_id": 1, "matches": 2},
        ],
        assets,
    ) == [{"item_id": 1, "matches": 2}]


def test_build_purchase_guide_handles_defaults_and_sorts_tiers() -> None:
    assets: list[dict[str, object]] = [
        {
            "id": 1,
            "item_tier": 1,
            "shopable": True,
            "shop_image_webp": "image",
        },
        {
            "id": 2,
            "item_tier": 1,
            "shopable": True,
            "shop_image_webp": "image",
            "name": "Named",
        },
    ]
    guide = purchase_windows.build_purchase_guide(
        {"id": 12},
        assets,
        [
            {"item_id": 1, "matches": 10, "wins": 5},
            {"item_id": 2, "matches": 20, "wins": 12},
        ],
        [{"item_id": 2, "bucket": 1_000, "matches": 20, "wins": 12}],
    )

    assert guide.hero_name == "Hero 12"
    assert not guide.hero_class_name
    assert [item.item_id for item in guide.tiers[1]] == [2, 1]
    assert guide.tiers[1][1].name == "Unknown Item"
