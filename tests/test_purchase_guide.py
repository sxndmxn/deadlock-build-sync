import pytest

from deadlock_build_sync.purchase_guide import (
    GuideItem,
    PurchaseBucketRow,
    analyze_purchase_windows,
    build_purchase_guide,
    choose_adaptive_bucket_increment,
    format_purchase_window,
    wilson_score_interval,
)


def evidence_item(
    *,
    q25: float | None = 3_935,
    q75: float | None = 13_724.25,
) -> GuideItem:
    return GuideItem(
        item_id=1,
        name="Mystic Expansion",
        tier=1,
        purchase_event_observations=12_611,
        observed_outcome_rate=0.4901276663,
        observed_outcome_lower_bound=0.0,
        relative_purchase_event_volume=0.8063814822,
        windows=(),
        eligible_player_matches=15_639,
        adopter_matches=12_611,
        purchase_adoption=0.8063814822,
        buy_net_worth_q25=q25,
        buy_net_worth_q75=q75,
    )


def test_evidence_item_annotation_is_compact_player_facing_copy() -> None:
    assert evidence_item().annotation == (
        "Purchase window: 4k–14k souls\nWin rate: 49.0%\nPick rate: 80.6%"
    )


def test_collapsed_and_missing_purchase_windows_remain_readable() -> None:
    assert evidence_item(q25=1_553, q75=2_449).annotation.startswith(
        "Purchase window: about 2k souls\n"
    )
    assert evidence_item(q25=None, q75=None).annotation.startswith(
        "Purchase window: unavailable\n"
    )


def test_wilson_interval_matches_known_value() -> None:
    low, high = wilson_score_interval(55, 100)
    assert low == pytest.approx(0.4524, abs=0.0001)
    assert high == pytest.approx(0.6439, abs=0.0001)


def test_adaptive_increment_and_central_buyer_distribution_ignore_outcome_peaks() -> (
    None
):
    rows = [
        PurchaseBucketRow(0, 5, 2),
        PurchaseBucketRow(1000, 25, 14),
        PurchaseBucketRow(2000, 25, 16),
        PurchaseBucketRow(3000, 25, 15),
        PurchaseBucketRow(4000, 10, 4),
    ]
    assert choose_adaptive_bucket_increment(rows, 100) == 1000
    windows = analyze_purchase_windows(rows, 100, 10_000)
    shifted_outcomes = [
        PurchaseBucketRow(row.bucket, row.matches, row.matches - row.wins)
        for row in rows
    ]
    shifted = analyze_purchase_windows(shifted_outcomes, 100, 10_000)
    assert [(window.bucket_start, window.bucket_end) for window in windows] == [
        (1000, 4000)
    ]
    assert [(window.bucket_start, window.bucket_end) for window in shifted] == [
        (1000, 4000)
    ]
    assert format_purchase_window(windows[0]) == "1–4k"


def test_guide_keeps_missing_timing_sorts_all_items_by_event_volume() -> None:
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
    assert len(guide.tiers[1]) == 10
    assert [item.item_id for item in guide.tiers[1]] == list(range(1000, 1010))
    assert guide.tiers[2][0].item_id == 2000
    assert not guide.tiers[2][0].windows
    assert "unavailable from aggregate telemetry" in guide.tiers[2][0].annotation
    assert "Relative event volume 100.0%" in guide.tiers[1][0].annotation
    assert "observed outcome rate" in guide.tiers[1][0].annotation
