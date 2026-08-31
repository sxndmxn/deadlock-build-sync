from __future__ import annotations

import math
from typing import TYPE_CHECKING

from .value_validation import integer

if TYPE_CHECKING:
    from collections.abc import Iterable

    from .ability_order import AbilityPath

from .purchase_types import (
    LOW_VOLUME_AVERAGE_SHARE,
    LOW_VOLUME_MATCHES,
    MIN_WINDOW_MATCHES,
    MIN_WINDOW_SHARE,
    NORMAL_AVERAGE_SHARE,
    PURCHASE_BUCKET_INCREMENTS,
    GroupedPurchaseBucket,
    GuideItem,
    PurchaseBucketRow,
    PurchaseGuide,
    PurchaseWindow,
)


def wilson_score_interval(
    wins: int, matches: int, z: float = 1.96
) -> tuple[float, float]:
    if matches == 0:
        return 0.0, 0.0
    phat = wins / matches
    z_squared = z * z
    z_squared_over_matches = z_squared / matches
    denominator = 1 + z_squared_over_matches
    center = phat + z_squared_over_matches * 0.5
    margin = z * math.sqrt(
        (phat * (1 - phat) + z_squared_over_matches * 0.25) / matches
    )
    return (center - margin) / denominator, (center + margin) / denominator


def group_purchase_buckets(
    rows: Iterable[PurchaseBucketRow],
    increment: int,
) -> list[GroupedPurchaseBucket]:
    groups: dict[int, tuple[int, int]] = {}
    for row in rows:
        if row.bucket is None or row.matches <= 0:
            continue
        key = (row.bucket // increment) * increment
        matches, wins = groups.get(key, (0, 0))
        groups[key] = matches + row.matches, wins + row.wins

    result: list[GroupedPurchaseBucket] = []
    for key, (matches, wins) in sorted(groups.items()):
        lower, _ = wilson_score_interval(wins, matches)
        result.append(
            GroupedPurchaseBucket(
                bucket_start=key,
                bucket_end=key + increment,
                matches=matches,
                wins=wins,
                observed_outcome_rate=wins / matches,
                wilson_lower_bound=lower,
            )
        )
    return result


def compute_average_bucket_matches(
    rows: Iterable[PurchaseBucketRow], increment: int
) -> float:
    groups = group_purchase_buckets(rows, increment)
    if not groups:
        return 0.0
    return sum(group.matches for group in groups) / len(groups)


def choose_adaptive_bucket_increment(
    rows: Iterable[PurchaseBucketRow],
    row_total_matches: int,
    increments: tuple[int, ...] = PURCHASE_BUCKET_INCREMENTS,
) -> int:
    rows = tuple(rows)
    fallback = increments[-1] if increments else 1000
    if row_total_matches <= 0:
        return fallback
    average_share = (
        NORMAL_AVERAGE_SHARE
        if row_total_matches > LOW_VOLUME_MATCHES
        else LOW_VOLUME_AVERAGE_SHARE
    )
    for increment in increments:
        if (
            compute_average_bucket_matches(rows, increment) / row_total_matches
            >= average_share
        ):
            return increment
    return fallback


def _weighted_median_purchase_net_worth(
    rows: Iterable[PurchaseBucketRow],
) -> int | None:
    sorted_rows = sorted(
        (row for row in rows if row.bucket is not None and row.matches > 0),
        key=lambda row: int(row.bucket or 0),
    )
    total_matches = sum(row.matches for row in sorted_rows)
    if total_matches == 0:
        return None
    running_matches = 0
    for row in sorted_rows:
        running_matches += row.matches
        if running_matches >= total_matches / 2:
            return int(row.bucket or 0) + 500
    return None


def calculate_tier_horizons(
    series: Iterable[tuple[int, Iterable[PurchaseBucketRow]]],
) -> dict[int, int]:
    by_tier: dict[int, list[PurchaseBucketRow]] = {}
    for tier, rows in series:
        by_tier.setdefault(tier, []).extend(rows)
    horizons: dict[int, int] = {}
    for tier, rows in by_tier.items():
        median = _weighted_median_purchase_net_worth(rows)
        if median is not None:
            horizons[tier] = math.ceil((median * 2) / 1000) * 1000
    return horizons


def _aggregate_window(
    groups: list[GroupedPurchaseBucket],
    start_index: int,
    end_index: int,
) -> PurchaseWindow:
    selected = groups[start_index : end_index + 1]
    matches = sum(group.matches for group in selected)
    wins = sum(group.wins for group in selected)
    lower, _ = wilson_score_interval(wins, matches)
    return PurchaseWindow(
        bucket_start=selected[0].bucket_start,
        bucket_end=selected[-1].bucket_end,
        matches=matches,
        wins=wins,
        observed_outcome_rate=wins / matches if matches else 0.0,
        wilson_lower_bound=lower,
    )


def select_purchase_windows(
    groups: list[GroupedPurchaseBucket],
    horizon: float,
    total_bucket_matches: int | None = None,
) -> list[PurchaseWindow]:
    if total_bucket_matches is None:
        total_bucket_matches = sum(group.matches for group in groups)
    minimum_matches = max(
        MIN_WINDOW_MATCHES, math.ceil(total_bucket_matches * MIN_WINDOW_SHARE)
    )
    eligible = [
        group
        for group in groups
        if group.bucket_end <= horizon and group.matches >= minimum_matches
    ]
    if not eligible:
        return []

    # This is a descriptive central range among observed purchase events, not a
    # recommended timing window. It deliberately ignores outcome peaks. True timing
    # recommendations require first-purchase risk sets (telemetry.py).
    total = sum(group.matches for group in eligible)
    lower_target = total * 0.25
    upper_target = total * 0.75
    cumulative = 0
    start_index = 0
    end_index = len(eligible) - 1
    for index, group in enumerate(eligible):
        cumulative += group.matches
        if cumulative >= lower_target:
            start_index = index
            break
    cumulative = 0
    for index, group in enumerate(eligible):
        cumulative += group.matches
        if cumulative >= upper_target:
            end_index = index
            break
    return [_aggregate_window(eligible, start_index, end_index)]


def analyze_purchase_windows(
    rows: Iterable[PurchaseBucketRow],
    row_total_matches: int,
    horizon: float,
) -> list[PurchaseWindow]:
    rows = tuple(rows)
    increment = choose_adaptive_bucket_increment(rows, row_total_matches)
    groups = group_purchase_buckets(rows, increment)
    total_bucket_matches = sum(row.matches for row in rows)
    return select_purchase_windows(groups, horizon, total_bucket_matches)


def _shopable_assets(assets: list[dict[str, object]]) -> dict[int, dict[str, object]]:
    eligible = [
        asset
        for asset in assets
        if asset.get("shopable")
        and not asset.get("disabled")
        and asset.get("shop_image_webp")
        and isinstance(asset.get("id"), int)
        and isinstance(asset.get("item_tier"), int)
        and 1 <= integer(asset["item_tier"]) <= 4
    ]
    return {integer(asset["id"]): asset for asset in eligible}


def _bucket_rows(
    rows: list[dict[str, object]],
    assets_by_id: dict[int, dict[str, object]],
) -> dict[int, list[PurchaseBucketRow]]:
    result: dict[int, list[PurchaseBucketRow]] = {}
    for row in rows:
        item_id = row.get("item_id")
        if not isinstance(item_id, int) or item_id not in assets_by_id:
            continue
        bucket = row.get("bucket")
        result.setdefault(item_id, []).append(
            PurchaseBucketRow(
                bucket=int(bucket) if isinstance(bucket, int) else None,
                matches=integer(row.get("matches"), default=0),
                wins=integer(row.get("wins"), default=0),
            )
        )
    return result


def _eligible_item_stats(
    rows: list[dict[str, object]],
    assets_by_id: dict[int, dict[str, object]],
) -> list[dict[str, object]]:
    return [
        row
        for row in rows
        if isinstance(row.get("item_id"), int)
        and integer(row["item_id"]) in assets_by_id
        and integer(row.get("matches"), default=0) > 0
    ]


def _guide_item_from_stats(
    row: dict[str, object],
    asset: dict[str, object],
    bucket_rows: list[PurchaseBucketRow],
    max_matches: int,
) -> GuideItem:
    item_id = integer(row["item_id"])
    matches = integer(row["matches"])
    wins = integer(row.get("wins"), default=0)
    lower, _ = wilson_score_interval(wins, matches)
    return GuideItem(
        item_id=item_id,
        name=str(asset.get("name") or "Unknown Item"),
        tier=integer(asset["item_tier"]),
        purchase_event_observations=matches,
        observed_outcome_rate=wins / matches,
        observed_outcome_lower_bound=lower,
        relative_purchase_event_volume=matches / max_matches,
        windows=tuple(analyze_purchase_windows(bucket_rows, matches, math.inf)),
    )


def _tiered_items(guide_items: list[GuideItem]) -> dict[int, tuple[GuideItem, ...]]:
    tiers: dict[int, tuple[GuideItem, ...]] = {}
    for tier in range(1, 5):
        tiers[tier] = tuple(
            sorted(
                (item for item in guide_items if item.tier == tier),
                key=lambda item: (
                    -item.relative_purchase_event_volume,
                    -item.observed_outcome_lower_bound,
                    -item.purchase_event_observations,
                    item.name.casefold(),
                ),
            )
        )
    return tiers


def build_purchase_guide(
    hero: dict[str, object],
    assets: list[dict[str, object]],
    overall_stats: list[dict[str, object]],
    bucket_stats: list[dict[str, object]],
    ability_path: AbilityPath | None = None,
) -> PurchaseGuide:
    assets_by_id = _shopable_assets(assets)
    bucket_rows_by_item = _bucket_rows(bucket_stats, assets_by_id)
    eligible_stats = _eligible_item_stats(overall_stats, assets_by_id)
    max_matches = max(
        (integer(row["matches"]) for row in eligible_stats),
        default=1,
    )

    guide_items: list[GuideItem] = []
    for row in eligible_stats:
        item_id = integer(row["item_id"])
        guide_items.append(
            _guide_item_from_stats(
                row,
                assets_by_id[item_id],
                bucket_rows_by_item.get(item_id, []),
                max_matches,
            )
        )

    return PurchaseGuide(
        hero_id=integer(hero["id"]),
        hero_name=str(hero.get("name") or f"Hero {hero['id']}"),
        hero_class_name=str(hero.get("class_name") or ""),
        tiers=_tiered_items(guide_items),
        ability_path=ability_path,
    )
