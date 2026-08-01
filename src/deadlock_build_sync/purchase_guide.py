from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable

    from .ability_order import AbilityPath

PURCHASE_BUCKET_INCREMENTS = (1000, 2000, 3000, 5000, 7000, 10000)
LOW_VOLUME_MATCHES = 200
NORMAL_AVERAGE_SHARE = 0.10
LOW_VOLUME_AVERAGE_SHARE = 0.15
MIN_WINDOW_MATCHES = 20
MIN_WINDOW_SHARE = 0.05
WINDOW_SCORE_TOLERANCE = 0.07
MAX_ITEMS_PER_TIER = 8


@dataclass(frozen=True)
class PurchaseBucketRow:
    bucket: int | None
    matches: int
    wins: int


@dataclass(frozen=True)
class GroupedPurchaseBucket:
    bucket_start: int
    bucket_end: int
    matches: int
    wins: int
    true_win_rate: float
    wilson_lower_bound: float


@dataclass(frozen=True)
class PurchaseWindow:
    bucket_start: int
    bucket_end: int
    matches: int
    wins: int
    true_win_rate: float
    wilson_lower_bound: float


@dataclass(frozen=True)
class GuideItem:
    item_id: int
    name: str
    tier: int
    overall_matches: int
    overall_win_rate: float
    overall_wilson_lower_bound: float
    relative_pick_rate: float
    windows: tuple[PurchaseWindow, ...]

    @property
    def annotation(self) -> str:
        windows = " • ".join(format_purchase_window(window) for window in self.windows)
        return f"{windows}\nPick {self.relative_pick_rate * 100:.1f}% | WR {self.overall_win_rate * 100:.1f}%"


@dataclass(frozen=True)
class PurchaseGuide:
    hero_id: int
    hero_name: str
    hero_class_name: str
    tiers: dict[int, tuple[GuideItem, ...]]
    ability_path: AbilityPath | None = None
    summary: str = ""
    tier_summaries: dict[int, str] = field(default_factory=dict)

    @property
    def item_count(self) -> int:
        return sum(len(items) for items in self.tiers.values())

    @property
    def has_complete_item_coverage(self) -> bool:
        return all(
            len(self.tiers.get(tier, ())) == MAX_ITEMS_PER_TIER for tier in range(1, 5)
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
                true_win_rate=wins / matches,
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
        true_win_rate=wins / matches if matches else 0.0,
        wilson_lower_bound=lower,
    )


def _ranges_overlap(first: PurchaseWindow, second: PurchaseWindow) -> bool:
    return (
        first.bucket_start < second.bucket_end
        and second.bucket_start < first.bucket_end
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

    peak_indexes: list[int] = []
    for index, group in enumerate(eligible):
        previous = eligible[index - 1] if index > 0 else None
        following = eligible[index + 1] if index + 1 < len(eligible) else None
        previous_score = (
            previous.wilson_lower_bound
            if previous is not None and previous.bucket_end == group.bucket_start
            else -math.inf
        )
        following_score = (
            following.wilson_lower_bound
            if following is not None and group.bucket_end == following.bucket_start
            else -math.inf
        )
        if (
            group.wilson_lower_bound >= previous_score
            and group.wilson_lower_bound >= following_score
        ):
            peak_indexes.append(index)

    candidates: dict[tuple[int, int], PurchaseWindow] = {}
    for peak_index in peak_indexes:
        peak = eligible[peak_index]
        floor = peak.wilson_lower_bound - WINDOW_SCORE_TOLERANCE
        start_index = peak_index
        end_index = peak_index
        while (
            start_index > 0
            and eligible[start_index - 1].bucket_end
            == eligible[start_index].bucket_start
            and eligible[start_index - 1].wilson_lower_bound >= floor
        ):
            start_index -= 1
        while (
            end_index < len(eligible) - 1
            and eligible[end_index].bucket_end == eligible[end_index + 1].bucket_start
            and eligible[end_index + 1].wilson_lower_bound >= floor
        ):
            end_index += 1
        candidate = _aggregate_window(eligible, start_index, end_index)
        candidates[candidate.bucket_start, candidate.bucket_end] = candidate

    selected: list[PurchaseWindow] = []
    ordered = sorted(
        candidates.values(),
        key=lambda window: (-window.wilson_lower_bound, -window.matches),
    )
    for candidate in ordered:
        if any(_ranges_overlap(window, candidate) for window in selected):
            continue
        selected.append(candidate)
        if len(selected) == 2:
            break
    return sorted(selected, key=lambda window: window.bucket_start)


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


def format_purchase_window(window: PurchaseWindow) -> str:
    start = round(window.bucket_start / 1000)
    end = round(window.bucket_end / 1000)
    return f"{start}–{end}k"


def build_purchase_guide(
    hero: dict[str, Any],
    assets: list[dict[str, Any]],
    overall_stats: list[dict[str, Any]],
    bucket_stats: list[dict[str, Any]],
    ability_path: AbilityPath | None = None,
) -> PurchaseGuide:
    shopable_assets = [
        asset
        for asset in assets
        if asset.get("shopable")
        and not asset.get("disabled")
        and asset.get("shop_image_webp")
        and isinstance(asset.get("id"), int)
        and isinstance(asset.get("item_tier"), int)
        and 1 <= int(asset["item_tier"]) <= 4
    ]
    assets_by_id = {int(asset["id"]): asset for asset in shopable_assets}
    bucket_rows_by_item: dict[int, list[PurchaseBucketRow]] = {}
    for row in bucket_stats:
        item_id = row.get("item_id")
        if not isinstance(item_id, int) or item_id not in assets_by_id:
            continue
        bucket = row.get("bucket")
        bucket_rows_by_item.setdefault(item_id, []).append(
            PurchaseBucketRow(
                bucket=int(bucket) if isinstance(bucket, int) else None,
                matches=int(row.get("matches") or 0),
                wins=int(row.get("wins") or 0),
            )
        )

    horizons = calculate_tier_horizons(
        (
            int(asset["item_tier"]),
            bucket_rows_by_item.get(int(asset["id"]), ()),
        )
        for asset in shopable_assets
    )
    eligible_stats = [
        row
        for row in overall_stats
        if isinstance(row.get("item_id"), int)
        and int(row["item_id"]) in assets_by_id
        and int(row.get("matches") or 0) > 0
    ]
    max_matches = max((int(row["matches"]) for row in eligible_stats), default=1)

    guide_items: list[GuideItem] = []
    for row in eligible_stats:
        item_id = int(row["item_id"])
        asset = assets_by_id[item_id]
        tier = int(asset["item_tier"])
        matches = int(row["matches"])
        wins = int(row.get("wins") or 0)
        windows = tuple(
            analyze_purchase_windows(
                bucket_rows_by_item.get(item_id, ()),
                matches,
                horizons.get(tier, math.inf),
            )
        )
        if not windows:
            continue
        lower, _ = wilson_score_interval(wins, matches)
        guide_items.append(
            GuideItem(
                item_id=item_id,
                name=str(asset.get("name") or "Unknown Item"),
                tier=tier,
                overall_matches=matches,
                overall_win_rate=wins / matches,
                overall_wilson_lower_bound=lower,
                relative_pick_rate=matches / max_matches,
                windows=windows,
            )
        )

    tiers: dict[int, tuple[GuideItem, ...]] = {}
    for tier in range(1, 5):
        tier_items = sorted(
            (item for item in guide_items if item.tier == tier),
            key=lambda item: (
                -item.relative_pick_rate,
                -item.overall_wilson_lower_bound,
                -item.overall_matches,
                item.name.casefold(),
            ),
        )
        tiers[tier] = tuple(tier_items[:MAX_ITEMS_PER_TIER])

    return PurchaseGuide(
        hero_id=int(hero["id"]),
        hero_name=str(hero.get("name") or f"Hero {hero['id']}"),
        hero_class_name=str(hero.get("class_name") or ""),
        tiers=tiers,
        ability_path=ability_path,
    )
