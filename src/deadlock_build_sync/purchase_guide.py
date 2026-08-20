from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable

    from .ability_order import AbilityPath
    from .build_evidence import (
        CoreAlternativeEvidence,
        ItemEvidence,
        SelectedHeroBuild,
    )

PURCHASE_BUCKET_INCREMENTS = (1000, 2000, 3000, 5000, 7000, 10000)
LOW_VOLUME_MATCHES = 200
NORMAL_AVERAGE_SHARE = 0.10
LOW_VOLUME_AVERAGE_SHARE = 0.15
MIN_WINDOW_MATCHES = 20
MIN_WINDOW_SHARE = 0.05
CORE_CATEGORY_DESCRIPTION = "AUTO QUEUE • Default path, buy left→right."
OPTIONAL_CORE_CATEGORY_DESCRIPTION = (
    "Excluded from Queue • Swap only when the card trigger applies."
)
TIER_CATEGORY_DESCRIPTION = "Excluded from Queue • Choose deliberately."
MAX_ITEM_ANNOTATION_BYTES = 240
MAX_CATEGORY_DESCRIPTION_BYTES = 240
MAX_TACTICAL_INSTRUCTION_BYTES = 165


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
    observed_outcome_rate: float
    wilson_lower_bound: float


@dataclass(frozen=True)
class PurchaseWindow:
    bucket_start: int
    bucket_end: int
    matches: int
    wins: int
    observed_outcome_rate: float
    wilson_lower_bound: float


@dataclass(frozen=True)
class TacticalProfile:
    primary_role: str
    fight_role: str
    economy_plan: str


@dataclass(frozen=True)
class GuideItem:
    item_id: int
    name: str
    tier: int
    purchase_event_observations: int
    observed_outcome_rate: float
    observed_outcome_lower_bound: float
    relative_purchase_event_volume: float
    windows: tuple[PurchaseWindow, ...]
    required_flex_slots: int | None = None
    sell_priority: int | None = None
    imbue_target_ability_id: int | None = None
    tactical_annotation: str = ""
    eligible_player_matches: int = 0
    adopter_matches: int = 0
    purchase_adoption: float = 0.0
    purchase_events: int = 0
    median_buy_time_s: float | None = None
    median_valid_buy_net_worth: float | None = None
    buy_net_worth_q25: float | None = None
    buy_net_worth_q75: float | None = None
    valid_buy_net_worth_share: float = 0.0

    @property
    def annotation(self) -> str:
        if self.tactical_annotation:
            return self.tactical_annotation
        if self.eligible_player_matches:
            return item_stat_context(self)
        timing = (
            " • ".join(format_purchase_window(window) for window in self.windows)
            if self.windows
            else "unavailable from aggregate telemetry"
        )
        return (
            f"Observed buyer purchase-event NW distribution: {timing}\n"
            f"Relative event volume {self.relative_purchase_event_volume * 100:.1f}% | "
            f"observed outcome rate {self.observed_outcome_rate * 100:.1f}%"
        )


@dataclass(frozen=True)
class GuideCategory:
    name: str
    items: tuple[GuideItem, ...]
    description: str = ""
    optional: bool = False


@dataclass(frozen=True)
class PurchaseGuide:
    hero_id: int
    hero_name: str
    hero_class_name: str
    tiers: dict[int, tuple[GuideItem, ...]]
    path_id: str = "default"
    path_label: str = "Evidence Default"
    signature_item_ids: tuple[int, ...] = ()
    ability_path: AbilityPath | None = None
    summary: str = ""
    tactical_profile: TacticalProfile | None = None
    tier_summaries: dict[int, str] = field(default_factory=dict)
    categories: tuple[GuideCategory, ...] = ()
    snapshot_id: str = ""
    policy_id: str = ""
    client_version: int | None = None
    match_mode: str = ""
    rank_identity: str = ""
    core_items: tuple[GuideItem, ...] = ()
    core_purchase_items: tuple[GuideItem, ...] = ()
    backbone_items: tuple[GuideItem, ...] = ()
    optional_core_items: tuple[GuideItem, ...] = ()
    core_alternatives: tuple[CoreAlternativeEvidence, ...] = ()
    backbone_matches: int = 0
    backbone_share: float = 0.0
    core_joint_matches: int = 0
    core_joint_share: float = 0.0
    median_final_net_worth: int = 0
    core_target_cost: int = 0
    build_tag_ids: tuple[int, ...] = ()
    build_tag_classes: tuple[str, ...] = ()
    build_tag_labels: tuple[str, ...] = ()
    build_tag_catalog_sha256: str = ""
    build_archetype: str = "Evidence Default"
    analysis_start_timestamp: int = 0
    as_of_timestamp: int = 0

    @property
    def item_count(self) -> int:
        if self.categories:
            return sum(len(category.items) for category in self.categories)
        return len(self.core_items) + sum(len(items) for items in self.tiers.values())

    @property
    def has_complete_item_coverage(self) -> bool:
        return all(self.tiers.get(tier) for tier in range(1, 5))

    @property
    def rendered_categories(self) -> tuple[GuideCategory, ...]:
        if self.categories:
            return self.categories
        if self.core_items:
            categories = [
                GuideCategory(
                    name="CORE ITEMS",
                    items=self.core_purchase_items or self.core_items,
                    description=CORE_CATEGORY_DESCRIPTION,
                )
            ]
            if self.optional_core_items:
                categories.append(
                    GuideCategory(
                        name="OPTIONAL CORE",
                        items=self.optional_core_items,
                        description=OPTIONAL_CORE_CATEGORY_DESCRIPTION,
                        optional=True,
                    )
                )
            categories.extend(
                GuideCategory(
                    name=f"TIER {tier}",
                    items=self.tiers.get(tier, ()),
                    description=TIER_CATEGORY_DESCRIPTION,
                    optional=True,
                )
                for tier in range(1, 5)
            )
            return tuple(categories)
        result: list[GuideCategory] = []
        for tier in range(1, 5):
            items = self.tiers.get(tier, ())
            if not items:
                continue
            summary = self.tier_summaries.get(tier, "")
            result.append(
                GuideCategory(
                    name=f"CORE {tier}",
                    items=items[:1],
                    description=summary,
                )
            )
            if len(items) > 1:
                result.append(
                    GuideCategory(
                        name=f"OPTIONS {tier}",
                        items=items[1:],
                        description="Situational alternatives; choose only when their trigger applies.",
                        optional=True,
                    )
                )
        return tuple(result)


def standard_category_description(name: str) -> str | None:
    """Return fixed player-facing copy for the standard policy layout.

    Returns:
        The fixed description, or ``None`` for a nonstandard policy category.

    """
    if name == "CORE ITEMS":
        return CORE_CATEGORY_DESCRIPTION
    if name == "OPTIONAL CORE":
        return OPTIONAL_CORE_CATEGORY_DESCRIPTION
    if name in {f"TIER {tier}" for tier in range(1, 5)}:
        return TIER_CATEGORY_DESCRIPTION
    return None


def _nearest_thousand(value: float) -> int:
    return math.floor(value / 1000 + 0.5)


def _format_observed_purchase_window(q25: float | None, q75: float | None) -> str:
    if q25 is None or q75 is None:
        return "unavailable"
    lower = _nearest_thousand(q25)
    upper = _nearest_thousand(q75)
    if lower == upper:
        return f"about {lower}k souls"
    return f"{lower}k–{upper}k souls"


def item_stat_context(item: GuideItem) -> str:
    """Render the compact analytics block shown under an item's native tooltip.

    Returns:
        Purchase window, raw buyer win rate, and player-match pick rate.

    """
    window = _format_observed_purchase_window(
        item.buy_net_worth_q25,
        item.buy_net_worth_q75,
    )
    return (
        f"PURCHASE WINDOW: {window}\n"
        f"WIN RATE: {item.observed_outcome_rate * 100:.1f}%\n"
        f"PICK RATE: {item.purchase_adoption * 100:.1f}%"
    )


def tactical_item_annotation(instruction: str, item: GuideItem) -> str:
    """Compose an action-first annotation within Steam's UTF-8 byte ceiling.

    Returns:
        The bounded tactical and observational annotation.

    Raises:
        ValueError: If the tactical instruction exceeds its UTF-8 contract.

    """
    action = instruction.strip()
    if not action or len(action.encode("utf-8")) > MAX_TACTICAL_INSTRUCTION_BYTES:
        raise ValueError(
            "tactical instruction must be 1–"
            f"{MAX_TACTICAL_INSTRUCTION_BYTES} UTF-8 bytes"
        )
    context = item_stat_context(item)
    combined = f"{action}\n{context}"
    annotation = (
        combined
        if len(combined.encode("utf-8")) <= MAX_ITEM_ANNOTATION_BYTES
        else context
    )
    if len(annotation.encode("utf-8")) > MAX_ITEM_ANNOTATION_BYTES:
        raise ValueError(
            f"item annotation exceeds {MAX_ITEM_ANNOTATION_BYTES} UTF-8 bytes"
        )
    return annotation


def guide_item_from_evidence(item: ItemEvidence) -> GuideItem:
    return GuideItem(
        item_id=item.item_id,
        name=item.item,
        tier=item.tier,
        purchase_event_observations=item.purchase_events,
        observed_outcome_rate=item.observed_outcome_rate,
        observed_outcome_lower_bound=0.0,
        relative_purchase_event_volume=item.adoption,
        windows=(),
        eligible_player_matches=item.eligible_player_matches,
        adopter_matches=item.adopter_matches,
        purchase_adoption=item.adoption,
        purchase_events=item.purchase_events,
        median_buy_time_s=item.median_buy_time_s,
        median_valid_buy_net_worth=item.median_valid_buy_net_worth,
        buy_net_worth_q25=item.buy_net_worth_q25,
        buy_net_worth_q75=item.buy_net_worth_q75,
        valid_buy_net_worth_share=item.valid_buy_net_worth_share,
    )


def build_purchase_guide_from_evidence(
    hero: dict[str, Any],
    selected: SelectedHeroBuild,
    *,
    ability_path: AbilityPath | None = None,
) -> PurchaseGuide:
    """Project validated player-match evidence into the analytic guide model.

    Returns:
        A state-aware economy-bounded default, optional swaps, and four adoption menus.

    """
    by_id = {
        item.item_id: guide_item_from_evidence(item)
        for items in selected.tiers.values()
        for item in items
    }
    for item in selected.core:
        by_id.setdefault(item.item_id, guide_item_from_evidence(item))
    for item in selected.core_purchase_path:
        by_id.setdefault(item.item_id, guide_item_from_evidence(item))
    for item in selected.optional_core:
        by_id.setdefault(item.item_id, guide_item_from_evidence(item))
    return PurchaseGuide(
        hero_id=int(hero["id"]),
        hero_name=str(hero.get("name") or f"Hero {hero['id']}"),
        hero_class_name=str(hero.get("class_name") or ""),
        tiers={
            tier: tuple(by_id[item.item_id] for item in items)
            for tier, items in selected.tiers.items()
        },
        path_id=selected.path_id,
        path_label=selected.path_label,
        signature_item_ids=selected.signature_item_ids,
        ability_path=ability_path,
        core_items=tuple(by_id[item.item_id] for item in selected.core),
        core_purchase_items=tuple(
            by_id[item.item_id] for item in selected.core_purchase_path
        ),
        backbone_items=tuple(by_id[item.item_id] for item in selected.backbone),
        optional_core_items=tuple(
            by_id[item.item_id] for item in selected.optional_core
        ),
        core_alternatives=selected.core_alternatives,
        backbone_matches=selected.backbone_matches,
        backbone_share=selected.backbone_share,
        core_joint_matches=selected.core_joint_matches,
        core_joint_share=selected.core_joint_share,
        median_final_net_worth=selected.median_final_net_worth,
        core_target_cost=selected.core_target_cost,
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


def format_purchase_window(window: PurchaseWindow) -> str:
    start = round(window.bucket_start / 1000)
    end = round(window.bucket_end / 1000)
    return f"{start}–{end}k"


def _shopable_assets(assets: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    eligible = [
        asset
        for asset in assets
        if asset.get("shopable")
        and not asset.get("disabled")
        and asset.get("shop_image_webp")
        and isinstance(asset.get("id"), int)
        and isinstance(asset.get("item_tier"), int)
        and 1 <= int(asset["item_tier"]) <= 4
    ]
    return {int(asset["id"]): asset for asset in eligible}


def _bucket_rows(
    rows: list[dict[str, Any]],
    assets_by_id: dict[int, dict[str, Any]],
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
                matches=int(row.get("matches") or 0),
                wins=int(row.get("wins") or 0),
            )
        )
    return result


def _eligible_item_stats(
    rows: list[dict[str, Any]],
    assets_by_id: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if isinstance(row.get("item_id"), int)
        and int(row["item_id"]) in assets_by_id
        and int(row.get("matches") or 0) > 0
    ]


def _guide_item_from_stats(
    row: dict[str, Any],
    asset: dict[str, Any],
    bucket_rows: list[PurchaseBucketRow],
    max_matches: int,
) -> GuideItem:
    item_id = int(row["item_id"])
    matches = int(row["matches"])
    wins = int(row.get("wins") or 0)
    lower, _ = wilson_score_interval(wins, matches)
    return GuideItem(
        item_id=item_id,
        name=str(asset.get("name") or "Unknown Item"),
        tier=int(asset["item_tier"]),
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
    hero: dict[str, Any],
    assets: list[dict[str, Any]],
    overall_stats: list[dict[str, Any]],
    bucket_stats: list[dict[str, Any]],
    ability_path: AbilityPath | None = None,
) -> PurchaseGuide:
    assets_by_id = _shopable_assets(assets)
    bucket_rows_by_item = _bucket_rows(bucket_stats, assets_by_id)
    eligible_stats = _eligible_item_stats(overall_stats, assets_by_id)
    max_matches = max((int(row["matches"]) for row in eligible_stats), default=1)

    guide_items: list[GuideItem] = []
    for row in eligible_stats:
        item_id = int(row["item_id"])
        guide_items.append(
            _guide_item_from_stats(
                row,
                assets_by_id[item_id],
                bucket_rows_by_item.get(item_id, []),
                max_matches,
            )
        )

    return PurchaseGuide(
        hero_id=int(hero["id"]),
        hero_name=str(hero.get("name") or f"Hero {hero['id']}"),
        hero_class_name=str(hero.get("class_name") or ""),
        tiers=_tiered_items(guide_items),
        ability_path=ability_path,
    )
