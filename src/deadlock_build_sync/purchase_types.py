from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .ability_order import AbilityPath
    from .build_evidence import (
        CoreAlternativeEvidence,
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
TIER_CATEGORY_DESCRIPTION = ""
MAX_ITEM_ANNOTATION_BYTES = 240
MAX_ITEM_ANNOTATION_CHARS = 200
POWER_SPIKE_LABEL = "POWER SPIKE"
MAX_CATEGORY_DESCRIPTION_BYTES = 240
MAX_TACTICAL_INSTRUCTION_BYTES = 165
CATEGORY_BASE_HEIGHT = 164.0
CATEGORY_ROW_HEIGHT = 155.5
CATEGORY_LAYOUTS = {
    "CORE ITEMS": (567.0, 6),
    "OPTIONAL CORE": (465.75, 5),
    "TIER 1": (465.75, 5),
    "TIER 2": (562.5, 5),
    "TIER 3": (465.75, 5),
    "TIER 4": (1039.5, 10),
}
DEFAULT_CATEGORY_LAYOUT = (760.0, 8)
CONDITIONAL_ANNOTATION_LABELS = ("VS", "WHY", "SWAP", "WHEN", "SKIP")
TIER_ANNOTATION_LABELS = ("USE", "WHY", "SKIP", "DATA")
_GENERIC_CONDITIONAL_PHRASES = (
    "documented mechanic",
    "fits the current fight",
    "observable need",
)


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
    conditional_annotation: str = ""
    verified_tier_annotation: str = ""
    power_spike: str = ""
    eligible_player_matches: int = 0
    adopter_matches: int = 0
    purchase_adoption: float = 0.0
    purchase_events: int = 0
    median_buy_time_s: float | None = None
    median_valid_buy_net_worth: float | None = None
    buy_net_worth_q25: float | None = None
    buy_net_worth_q75: float | None = None
    valid_buy_net_worth_share: float = 0.0
    imbue_target_ability: str | None = None
    imbue_target_matches: int = 0
    imbue_observations: int = 0
    imbue_target_share: float = 0.0

    @property
    def annotation(self) -> str:
        if self.conditional_annotation:
            return self.conditional_annotation
        body = self.verified_tier_annotation or self._evidence_annotation()
        if self.power_spike:
            return f"{POWER_SPIKE_LABEL}: {self.power_spike}\n{body}"
        return body

    def _evidence_annotation(self) -> str:
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
    width: float = field(init=False)
    height: float = field(init=False)

    def __post_init__(self) -> None:
        """Resolve the Steam tile area from the item count."""
        width, columns = CATEGORY_LAYOUTS.get(self.name, DEFAULT_CATEGORY_LAYOUT)
        rows = max(1, math.ceil(len(self.items) / columns))
        object.__setattr__(self, "width", width)
        object.__setattr__(
            self,
            "height",
            CATEGORY_BASE_HEIGHT + CATEGORY_ROW_HEIGHT * (rows - 1),
        )


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
    lines = [
        f"PURCHASE WINDOW: {window}",
        f"WIN RATE: {item.observed_outcome_rate * 100:.1f}%",
        f"PICK RATE: {item.purchase_adoption * 100:.1f}%",
        f"BUYER MATCHES: {item.adopter_matches:,}",
        f"PURCHASE EVENTS: {item.purchase_events:,}",
    ]
    if item.imbue_target_ability:
        lines.append(
            f"IMBUE: {item.imbue_target_ability} "
            f"({item.imbue_target_share * 100:.1f}%, n={item.imbue_observations:,})"
        )
    return "\n".join(lines)


def format_purchase_window(window: PurchaseWindow) -> str:
    start = round(window.bucket_start / 1000)
    end = round(window.bucket_end / 1000)
    return f"{start}–{end}k"
