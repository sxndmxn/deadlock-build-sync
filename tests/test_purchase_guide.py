from dataclasses import replace

import pytest

from deadlock_build_sync.purchase_guide import (
    GuideCategory,
    GuideItem,
    PurchaseBucketRow,
    analyze_purchase_windows,
    build_purchase_guide,
    choose_adaptive_bucket_increment,
    conditional_item_annotation,
    format_purchase_window,
    standard_category_description,
    wilson_score_interval,
)
from deadlock_build_sync.snapshot import sha256_json


def test_standard_category_copy_keeps_the_public_description_contract() -> None:
    names = [
        "CORE ITEMS",
        "OPTIONAL CORE",
        *[f"TIER {tier}" for tier in range(1, 5)],
        "CUSTOM",
    ]
    assert sha256_json({
        name: standard_category_description(name) for name in names
    }) == ("79cf24aec347383c5a9004bd937bdb14bafbbaa7c620d368d6d53583e41d5aa4")


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
        purchase_events=12_700,
        buy_net_worth_q25=q25,
        buy_net_worth_q75=q75,
    )


def test_every_item_card_is_the_two_line_statistics_block() -> None:
    assert evidence_item().annotation == (
        "SOUL WINDOW: 4k - 14k\nPR: 80.6% | WR: 49.0% | TOTAL GAMES: 12,611"
    )
    assert len(evidence_item().annotation.encode("utf-8")) <= 240


def test_the_card_carries_no_generated_copy_or_imbue_line() -> None:
    item = replace(
        evidence_item(),
        imbue_target_ability_id=40,
        imbue_target_ability="Frozen Shelter",
        imbue_target_matches=75,
        imbue_observations=100,
        imbue_target_share=0.75,
    )

    assert item.annotation == evidence_item().annotation
    assert "IMBUE" not in item.annotation
    assert "USE:" not in item.annotation


def test_collapsed_and_missing_purchase_windows_remain_readable() -> None:
    assert evidence_item(q25=1_553, q75=2_449).annotation.startswith(
        "SOUL WINDOW: about 2k\n"
    )
    assert evidence_item(q25=None, q75=None).annotation.startswith(
        "SOUL WINDOW: unavailable\n"
    )


def test_conditional_annotation_keeps_its_fixed_policy_sidecar_lines() -> None:
    annotation = conditional_item_annotation(
        vs="Heavy Spirit damage",
        why="Spirit Resist and Debuff Resist for self/ally",
        swap="Replaces Phantom Strike",
        when="Before the next Spirit-heavy fight",
        skip="Keep default when catch matters more",
    )

    assert annotation == (
        "VS: Heavy Spirit damage\n"
        "WHY: Spirit Resist and Debuff Resist for self/ally\n"
        "SWAP: Replaces Phantom Strike\n"
        "WHEN: Before the next Spirit-heavy fight\n"
        "SKIP: Keep default when catch matters more"
    )
    assert len(annotation.encode("utf-8")) <= 240


def test_conditional_annotation_rejects_generic_or_oversized_copy() -> None:
    with pytest.raises(ValueError, match="generic trigger"):
        conditional_item_annotation(
            vs="When its documented mechanic fits the current fight",
            why="Spirit Resist",
            swap="Replaces Phantom Strike",
            when="Before the next fight",
            skip="Keep default when catch matters more",
        )
    with pytest.raises(ValueError, match="240"):
        conditional_item_annotation(
            vs="x" * 241,
            why="Spirit Resist",
            swap="Replaces Phantom Strike",
            when="Before the next fight",
            skip="Keep default when catch matters more",
        )


@pytest.mark.parametrize(
    ("name", "count", "expected_width", "expected_height"),
    [
        ("CORE ITEMS", 1, 567.0, 164.0),
        ("CORE ITEMS", 6, 567.0, 164.0),
        ("CORE ITEMS", 12, 567.0, 319.5),
        ("CORE ITEMS", 13, 567.0, 475.0),
        ("OPTIONAL CORE", 5, 465.75, 164.0),
        ("OPTIONAL CORE", 6, 465.75, 319.5),
        ("TIER 1", 10, 465.75, 319.5),
        ("CORE ITEMS", 16, 567.0, 475.0),
        ("TIER 4", 10, 1039.5, 164.0),
        ("TIER 4", 17, 1039.5, 319.5),
    ],
)
def test_category_dimensions_follow_item_count(
    name: str,
    count: int,
    expected_width: float,
    expected_height: float,
) -> None:
    category = GuideCategory(name, tuple(evidence_item() for _ in range(count)))

    assert category.width == expected_width
    assert category.height == expected_height


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
    assets: list[dict[str, object]] = []
    overall: list[dict[str, object]] = []
    buckets: list[dict[str, object]] = []
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
