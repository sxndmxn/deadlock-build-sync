import pytest

from deadlock_build_sync.purchase_guide import (
    PurchaseBucketRow,
    analyze_purchase_windows,
    build_purchase_guide,
    choose_adaptive_bucket_increment,
    format_purchase_window,
    wilson_score_interval,
)


def test_wilson_interval_matches_known_value() -> None:
    low, high = wilson_score_interval(55, 100)
    assert low == pytest.approx(0.4524, abs=0.0001)
    assert high == pytest.approx(0.6439, abs=0.0001)


def test_adaptive_increment_and_window_selection() -> None:
    rows = [
        PurchaseBucketRow(0, 5, 2),
        PurchaseBucketRow(1000, 25, 14),
        PurchaseBucketRow(2000, 25, 16),
        PurchaseBucketRow(3000, 25, 15),
        PurchaseBucketRow(4000, 10, 4),
    ]
    assert choose_adaptive_bucket_increment(rows, 100) == 1000
    windows = analyze_purchase_windows(rows, 100, 10_000)
    assert windows
    assert format_purchase_window(windows[0]).endswith("k")


def test_guide_excludes_missing_windows_sorts_and_caps() -> None:
    assets = []
    overall = []
    buckets = []
    for index in range(10):
        item_id = 1000 + index
        assets.append({
            "id": item_id,
            "name": f"Item {index}",
            "item_tier": 1,
            "shopable": True,
            "disabled": False,
            "shop_image_webp": "https://example.invalid/item.webp",
        })
        overall.append({"item_id": item_id, "matches": 100 - index, "wins": 50})
        buckets.extend([
            {"item_id": item_id, "bucket": 1000, "matches": 50, "wins": 30},
            {"item_id": item_id, "bucket": 2000, "matches": 50, "wins": 31},
        ])
    assets.append({
        "id": 2000,
        "name": "No Window",
        "item_tier": 2,
        "shopable": True,
        "disabled": False,
        "shop_image_webp": "https://example.invalid/item.webp",
    })
    overall.append({"item_id": 2000, "matches": 99, "wins": 60})

    guide = build_purchase_guide(
        {"id": 12, "name": "Kelvin", "class_name": "hero_kelvin"},
        assets,
        overall,
        buckets,
    )
    assert len(guide.tiers[1]) == 8
    assert [item.item_id for item in guide.tiers[1]] == list(range(1000, 1008))
    assert not guide.tiers[2]
    assert "Pick 100.0%" in guide.tiers[1][0].annotation
