"""Typed records for core discovery, build selection, and item pool evidence."""

from __future__ import annotations

from typing import TypedDict

type ItemsetSupportCounts = dict[tuple[int, ...], int]
type HeroLandmarkRow = tuple[
    int, int, str, bool, float | None, float | None, int, float | None, list[int] | None
]
type FirstPurchaseRow = tuple[int, int, int, int, float | None, int | None]


class DiscoveryItemAsset(TypedDict):
    name: str
    cost: int
    ancestors: list[int]


type DiscoveryItemCatalog = dict[str, DiscoveryItemAsset]


class AdjustedOutcomeEstimate(TypedDict, total=False):
    core_overlap: int
    overlap_share: float
    strata: int
    difference: float | None
    lower_95: float | None
    p_greater: float
    standard_error: float
    core_rate: float
    noncore_rate: float


class CoreEvaluation(TypedDict, total=False):
    fold: str
    rows: int
    owners: int
    wins: int
    win_rate: float | None
    hero_win_rate: float | None
    coverage: float
    joint_lift: float
    win_lower_95: float
    win_p_greater_half: float
    adjusted: AdjustedOutcomeEstimate
    adjusted_lower_family: float | None


class OrderEvidence(TypedDict):
    owners: int
    ordered_owners: int
    share: float
    passes: bool


class SelectedPurchaseOrder(TypedDict, total=False):
    method: str
    order: list[int]
    ranking_score: int
    discovery: OrderEvidence
    selection: OrderEvidence
    admitted_before_validation: bool
    legal: bool
    actions: list[dict[str, object]]
    illegal_orders_skipped: int
    reason: str | None


class CoreDiscoveryCandidate(TypedDict, total=False):
    items: list[int]
    names: list[str]
    cost: int
    discovery_support: int
    discovery_lift: float
    score: float
    parent: list[int]
    parent_retention: float | None
    identity_id: str
    selection: CoreEvaluation
    selection_rejections: list[str]


class CoreGroupingResult(TypedDict):
    groups: list[list[int]]
    seeds: list[dict[str, int | list[int]]]
    edges: list[dict[str, int | float]]
    candidate_order: list[list[int]]


class CoreMiningResult(TypedDict):
    candidates: list[CoreDiscoveryCandidate]
    sizes: dict[str, dict[str, int]]


class DiscoveryReport(TypedDict):
    sizes: dict[str, dict[str, int]]
    seeds: list[CoreDiscoveryCandidate]
    candidates: list[CoreDiscoveryCandidate]
    grouping: CoreGroupingResult
    mine_seconds: float
    group_seconds: float
    selected: dict[str, list[int]]


class ItemPoolStatistics(TypedDict):
    buyers: int
    adoption: float
    time_seconds_q25_q50_q75: list[float]
    fresh_wealth_observations: int
    net_worth_q25_q50_q75: list[float] | None


class ItemPoolEvidence(TypedDict):
    population: int
    items: dict[int, ItemPoolStatistics]
    histories: dict[tuple[int, int], dict[int, float]]


class PurchasePlacementEvidence(TypedDict):
    after_step: int | None
    observed_after_step: int
    support: int
    buyers: int
    supported: bool
    counts_by_checkpoint: list[int]
    basis: str


class FrozenPurchaseGuide(TypedDict, total=False):
    timing_status: str
    ready: bool
    reason: str | None
    path: list[int]
    pool: dict[str, list[int]]
    discovery_buyers: int
    bounds: dict[str, list[float]]
    pool_statistics: dict[str, ItemPoolStatistics]
    purchase_timing: dict[str, object]


class MechanicOverlapEvidence(TypedDict):
    supported_focus: bool
    focuses: list[dict[str, object]]
    item_evidence: dict[str, dict[str, dict[str, object]]]
    reason: str | None
    limitation: str


class NominatedCoreBuild(CoreDiscoveryCandidate, total=False):
    evidence_status: str
    evidence_limitations: list[str]
    hero_id: int
    selection_rank: int
    path: SelectedPurchaseOrder
    tactics: MechanicOverlapEvidence
    guide: FrozenPurchaseGuide
    validation: CoreEvaluation
    order_validation: OrderEvidence
    hypotheses: int
    rejections: list[str]
    branch_candidates: list[dict[str, object]]
    automatic_choices: dict[str, object]
    frozen_sha256: str


class FrozenHeroDiscovery(TypedDict):
    cohort: dict[str, object]
    rows: list[NominatedCoreBuild]
    candidate_count: int
    grouping: CoreGroupingResult
    candidates: list[CoreDiscoveryCandidate]
