from dataclasses import replace

import pytest

from deadlock_build_sync import purchase_annotations
from deadlock_build_sync.purchase_guide import (
    GuideCategory,
    GuideItem,
    PurchaseBucketRow,
    analyze_purchase_windows,
    build_purchase_guide,
    choose_adaptive_bucket_increment,
    conditional_item_annotation,
    format_purchase_window,
    split_power_spike,
    tactical_item_annotation,
    tier_item_annotation,
    validate_tier_annotation,
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
        purchase_events=12_700,
        buy_net_worth_q25=q25,
        buy_net_worth_q75=q75,
    )


def test_evidence_item_annotation_is_compact_player_facing_copy() -> None:
    assert evidence_item().annotation == (
        "PURCHASE WINDOW: 4k–14k souls\n"
        "WIN RATE: 49.0%\n"
        "PICK RATE: 80.6%\n"
        "BUYER MATCHES: 12,611\n"
        "PURCHASE EVENTS: 12,700"
    )


def test_item_annotation_uses_stats_and_observed_imbue_target_only() -> None:
    item = evidence_item()
    item = replace(
        item,
        tactical_annotation="AI prose must not appear.",
        imbue_target_ability_id=40,
        imbue_target_ability="Frozen Shelter",
        imbue_target_matches=75,
        imbue_observations=100,
        imbue_target_share=0.75,
    )

    assert "AI prose" not in item.annotation
    assert item.annotation.endswith("IMBUE: Frozen Shelter (75.0%, n=100)")


def test_verified_tier_annotation_replaces_raw_win_rate_stats() -> None:
    item = evidence_item()
    annotation = tier_item_annotation(
        use="Spirit pressure is your next priority",
        why="Spirit Power",
        skip="Defense or weapon pressure matters more",
        item=item,
    )
    item = replace(item, verified_tier_annotation=annotation)

    assert item.annotation == (
        "USE: Spirit pressure is your next priority\n"
        "WHY: Spirit Power\n"
        "SKIP: Defense or weapon pressure matters more\n"
        "DATA: 4k–14k souls • PICK 80.6% • BUYERS 12,611"
    )
    assert "WIN RATE" not in item.annotation
    validate_tier_annotation(item.annotation)


def test_power_spike_line_leads_core_and_tier_hovers_but_not_conditional() -> None:
    core = replace(evidence_item(), power_spike="Napalm spirit x0.6")
    assert core.annotation.startswith(
        "POWER SPIKE: Napalm spirit x0.6\nPURCHASE WINDOW: "
    )

    card = tier_item_annotation(
        use="Spirit pressure is your next priority",
        why="Spirit Power",
        skip="Defense or weapon pressure matters more",
        item=evidence_item(),
    )
    tier = replace(evidence_item(), verified_tier_annotation=card, power_spike="X")
    assert tier.annotation.splitlines()[:2] == [
        "POWER SPIKE: X",
        "USE: Spirit pressure is your next priority",
    ]
    assert split_power_spike(tier.annotation) == ("X", card)
    validate_tier_annotation(split_power_spike(tier.annotation)[1])

    conditional = conditional_item_annotation(
        vs="Heavy Spirit damage",
        why="Spirit Resist for self",
        swap="Replaces Phantom Strike",
        when="Before the next Spirit-heavy fight",
        skip="Keep default when catch matters more",
    )
    swap = replace(evidence_item(), conditional_annotation=conditional, power_spike="X")
    assert swap.annotation == conditional
    assert split_power_spike(conditional) == ("", conditional)


@pytest.mark.parametrize("annotation", ["POWER SPIKE: \nUSE: x", "POWER SPIKE: x"])
def test_split_power_spike_rejects_empty_text_or_body(annotation: str) -> None:
    with pytest.raises(ValueError, match="power spike line"):
        split_power_spike(annotation)


def test_overlong_spike_is_dropped_while_the_tier_card_survives() -> None:
    asset: dict[str, object] = {
        "id": 1,
        "name": "Mystic Expansion",
        "description": {"desc": "Gain Spirit Power."},
        "properties": {
            "TechPower": {
                "provided_property_type": "MODIFIER_VALUE_TECH_POWER",
                "tooltip_is_important": True,
                "value": "10",
            }
        },
    }
    scale = {"class_name": "scale_function_tech_damage", "stat_scale": 0.6}

    def kit(name: str) -> dict[str, object]:
        return {
            "abilities": [
                {
                    "id": 10,
                    "slot": 1,
                    "name": name,
                    "properties": {"Damage": {"value": 40.0, "scale_function": scale}},
                }
            ]
        }

    projected = purchase_annotations._annotated_tier_item(
        evidence_item(), asset, kit("A" * 120)
    )
    assert projected is not None
    assert not projected.power_spike
    assert projected.annotation.startswith("USE: ")
    validate_tier_annotation(projected.annotation)

    spiked = purchase_annotations._annotated_tier_item(
        evidence_item(), asset, kit("Napalm")
    )
    assert spiked is not None
    assert spiked.annotation.startswith("POWER SPIKE: Napalm spirit x0.6\nUSE: ")
    assert len(spiked.annotation) <= 200


def test_tier_annotation_rejects_unstructured_or_oversized_copy() -> None:
    with pytest.raises(ValueError, match="USE, WHY, SKIP, and DATA"):
        validate_tier_annotation("AI prose")
    with pytest.raises(ValueError, match="240"):
        tier_item_annotation(
            use="x" * 241,
            why="Spirit Power",
            skip="Defense matters more",
            item=evidence_item(),
        )


def test_collapsed_and_missing_purchase_windows_remain_readable() -> None:
    assert evidence_item(q25=1_553, q75=2_449).annotation.startswith(
        "PURCHASE WINDOW: about 2k souls\n"
    )


def test_tactical_copy_keeps_the_complete_stats_block() -> None:
    item = evidence_item()

    assert tactical_item_annotation("x" * 165, item).endswith(item.annotation)
    assert evidence_item(q25=None, q75=None).annotation.startswith(
        "PURCHASE WINDOW: unavailable\n"
    )


def test_conditional_annotation_replaces_stats_with_fixed_decision_lines() -> None:
    annotation = conditional_item_annotation(
        vs="Heavy Spirit damage",
        why="Spirit Resist and Debuff Resist for self/ally",
        swap="Replaces Phantom Strike",
        when="Before the next Spirit-heavy fight",
        skip="Keep default when catch matters more",
    )
    item = replace(evidence_item(), conditional_annotation=annotation)

    assert item.annotation == (
        "VS: Heavy Spirit damage\n"
        "WHY: Spirit Resist and Debuff Resist for self/ally\n"
        "SWAP: Replaces Phantom Strike\n"
        "WHEN: Before the next Spirit-heavy fight\n"
        "SKIP: Keep default when catch matters more"
    )
    assert len(item.annotation.encode("utf-8")) <= 240
    assert "WIN RATE" not in item.annotation
    assert "WIN RATE" in evidence_item().annotation


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
