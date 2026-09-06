"""Closed internal values for discovery, nomination, and pool evidence."""

from __future__ import annotations

from typing import TypedDict

type PatternCounts = dict[tuple[int, ...], int]
type LandmarkRow = tuple[int, int, str, bool, float, float, int, float, list[int]]
type PurchaseRow = tuple[int, int, int, int, float | None, int | None]


class CatalogAsset(TypedDict):
    name: str
    cost: int
    ancestors: list[int]


type Catalog = dict[str, CatalogAsset]


class Adjusted(TypedDict, total=False):
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
    adjusted: Adjusted
    adjusted_lower_family: float | None


class OrderEvidence(TypedDict):
    owners: int
    ordered_owners: int
    share: float
    passes: bool


class Order(TypedDict, total=False):
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


class Candidate(TypedDict, total=False):
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


class Grouping(TypedDict):
    groups: list[list[int]]
    seeds: list[dict[str, int | list[int]]]
    edges: list[dict[str, int | float]]
    candidate_order: list[list[int]]


class Mining(TypedDict):
    candidates: list[Candidate]
    sizes: dict[str, dict[str, int]]


class DiscoveryReport(TypedDict):
    sizes: dict[str, dict[str, int]]
    seeds: list[Candidate]
    candidates: list[Candidate]
    grouping: Grouping
    mine_seconds: float
    group_seconds: float
    selected: dict[str, list[int]]


class PoolStat(TypedDict):
    buyers: int
    adoption: float
    time_seconds_q25_q50_q75: list[float]
    fresh_wealth_observations: int
    net_worth_q25_q50_q75: list[float] | None


class PoolEvidence(TypedDict):
    population: int
    items: dict[int, PoolStat]
    histories: dict[tuple[int, int], dict[int, float]]


class Placement(TypedDict):
    after_step: int | None
    observed_after_step: int
    support: int
    buyers: int
    supported: bool
    counts_by_checkpoint: list[int]
    basis: str


class FrozenGuide(TypedDict, total=False):
    ready: bool
    reason: str | None
    path: list[int]
    pool: dict[str, list[int]]
    discovery_buyers: int
    bounds: dict[str, list[float]]
    pool_statistics: dict[str, PoolStat]
    purchase_timing: dict[str, object]


class Tactics(TypedDict):
    supported_focus: bool
    focuses: list[dict[str, object]]
    item_evidence: dict[str, dict[str, dict[str, object]]]
    reason: str | None
    limitation: str


class Nomination(Candidate, total=False):
    hero_id: int
    selection_rank: int
    path: Order
    tactics: Tactics
    guide: FrozenGuide
    validation: CoreEvaluation
    order_validation: OrderEvidence
    hypotheses: int
    rejections: list[str]
    branch_candidates: list[dict[str, object]]
    automatic_choices: dict[str, object]
    frozen_sha256: str


class FrozenHero(TypedDict):
    rows: list[Nomination]
    candidate_count: int
    grouping: Grouping
    candidates: list[Candidate]
