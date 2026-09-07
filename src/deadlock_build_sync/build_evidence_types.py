from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from .artifacts import ArtifactError
from .build_support import SUPPORT
from .core_alternative_types import CoreAlternativeDescription

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from .hero_cohort import HeroCohort
    from .match_choices import AutomaticBranch
    from .purchase_guidance_types import PurchaseTiming
    from .snapshot import EpochSet

BUILD_EVIDENCE_SCHEMA_VERSION = 11
MAXIMUM_CORE_ITEM_COUNT = 9
TIER_ITEM_COUNT = SUPPORT.pool_limit
MINIMUM_TIER_SUPPORT = SUPPORT.pool_buyers
MINIMUM_TIER_ADOPTION = 0.05
MAXIMUM_TIER_ADOPTION_DRIFT = 0.10
MINIMUM_PURCHASE_WINDOW_COVERAGE = 0.50
MINIMUM_PURCHASE_WINDOW_OBSERVATIONS = 20
MINIMUM_CORE_SUPPORT = 20
METHOD_VERSION = "eclat-leiden-pairwise-v2"
SEQUENCE_POLICY_VERSION = 3
SITUATIONAL_POLICY_VERSION = 2
CORE_POLICY_VERSION = 3
TIER_POLICY_VERSION = 1
MINIMUM_BACKBONE_ITEM_COUNT = 3
MAXIMUM_BACKBONE_ITEM_COUNT = 6
MINIMUM_IMBUE_SUPPORT = 20
MINIMUM_IMBUE_SHARE = 0.5
MAXIMUM_CORE_ALTERNATIVES = 10
MAX_SITUATIONAL_BRANCHES = 7
MAX_COMPARATIVE_INTERVAL_WIDTH = 0.10
SEQUENCE_LEVELS = (
    "first_previous_position",
    "previous_position",
    "position",
    "popularity",
)
THREAT_CLASSES = frozenset({
    "healing",
    "bullet_pressure",
    "spirit_pressure",
    "control",
    "mobility_escape",
    "mobility_denial",
    "ally_protection",
    "active_slot_burden",
})
MECHANIC_RESPONSE_THREATS = {
    "hard_control": "control",
    "healing": "healing",
    "bullet_pressure": "bullet_pressure",
    "spirit_burst": "spirit_pressure",
    "mobility_denial": "mobility_escape",
    "slow_resistance": "mobility_denial",
    "ally_protection": "ally_protection",
}


@dataclass(frozen=True)
class ItemEvidence:
    item_id: int
    item: str
    tier: int
    cost: int
    slot: str
    active: bool
    adopter_matches: int
    eligible_player_matches: int
    purchase_events: int
    wins: int
    adoption: float
    observed_outcome_rate: float
    median_buy_time_s: float
    median_valid_buy_net_worth: float | None
    buy_net_worth_q25: float | None
    buy_net_worth_q75: float | None
    valid_buy_net_worth_share: float
    selection_adopter_matches: int
    selection_eligible_player_matches: int
    training_adopter_matches: int
    training_eligible_player_matches: int
    validation_adopter_matches: int
    validation_eligible_player_matches: int
    test_adopter_matches: int
    test_eligible_player_matches: int
    selection_adoption: float
    training_adoption: float
    validation_adoption: float
    test_adoption: float
    selection_median_buy_time_s: float | None
    selection_median_valid_buy_net_worth: float | None
    selection_buy_net_worth_q25: float | None
    selection_buy_net_worth_q75: float | None
    selection_valid_buy_net_worth_share: float
    selection_valid_buy_net_worth_observations: int
    training_valid_buy_net_worth_observations: int
    validation_valid_buy_net_worth_observations: int
    training_buy_net_worth_q25: float | None
    training_buy_net_worth_q75: float | None
    validation_buy_net_worth_q25: float | None
    validation_buy_net_worth_q75: float | None
    imbue_target_ability_id: int | None = None
    imbue_target_ability: str | None = None
    imbue_target_matches: int = 0
    imbue_observations: int = 0
    imbue_target_share: float = 0.0


def reliable_purchase_window(item: ItemEvidence) -> tuple[float, float] | None:
    lower = item.selection_buy_net_worth_q25
    upper = item.selection_buy_net_worth_q75
    train_lower = item.training_buy_net_worth_q25
    train_upper = item.training_buy_net_worth_q75
    validation_lower = item.validation_buy_net_worth_q25
    validation_upper = item.validation_buy_net_worth_q75
    if (
        item.selection_valid_buy_net_worth_share < MINIMUM_PURCHASE_WINDOW_COVERAGE
        or item.training_valid_buy_net_worth_observations
        < MINIMUM_PURCHASE_WINDOW_OBSERVATIONS
        or item.validation_valid_buy_net_worth_observations
        < MINIMUM_PURCHASE_WINDOW_OBSERVATIONS
    ):
        return None
    if lower is None or upper is None:
        return None
    if (
        train_lower is None
        or train_upper is None
        or validation_lower is None
        or validation_upper is None
        or max(train_lower, validation_lower) > min(train_upper, validation_upper)
    ):
        return None
    return lower, upper


@dataclass(frozen=True)
class CoreCandidate:
    item_ids: tuple[int, ...]
    joint_matches: int


@dataclass(frozen=True)
class CoreAlternativeEvidence(CoreAlternativeDescription):
    item_id: int
    comparator_item_id: int
    stage: int
    support: int
    comparison_support: int
    effective_support: float
    overlap: float
    stable: bool
    dr_estimate: float
    comparative_interval: tuple[float, float]
    fold_estimates: dict[str, float]
    fold_diagnostics: dict[str, dict[str, object]] = field(default_factory=dict)


@dataclass(frozen=True)
class CorePolicyEvidence:
    backbone_item_ids: tuple[int, ...]
    default_item_ids: tuple[int, ...]
    backbone_matches: int
    backbone_fold_matches: dict[str, int]
    default_matches: int
    alternatives: tuple[CoreAlternativeEvidence, ...]
    candidate_audit: tuple[dict[str, object], ...]
    evaluation: dict[str, object]
    default_fold_matches: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class TierPolicyEvidence:
    item_ids_by_tier: dict[int, tuple[int, ...]]
    discovery_pool: bool = False


@dataclass(frozen=True)
class SequenceTransition:
    level: str
    first_item_id: int
    previous_item_id: int
    position: int
    next_item_id: int
    support: int
    context_support: int


@dataclass(frozen=True)
class SequencePolicy:
    default_path: tuple[int, ...]
    transitions: tuple[SequenceTransition, ...]
    minimum_support: int
    production_model: str
    evaluation: dict[str, object]


@dataclass(frozen=True)
class SituationalBranch:
    threat: str
    item_id: int
    enemy_hero_id: int | None
    mechanic_ref: str
    comparator: str
    comparator_item_id: int
    comparison_support: int
    same_opportunity: bool
    support: int
    effective_support: float
    overlap: float
    stable: bool
    comparative_interval: tuple[float, float]
    trigger: str
    replacement: str
    execution: str
    failure_condition: str
    enemy_scope: str = "whole_enemy_team"
    phase: int = 0
    tier: int = 1
    enemy_mechanics_refs: tuple[str, ...] = ()
    fold_comparative_estimates: dict[str, float] = field(default_factory=dict)
    fold_support: dict[str, dict[str, int]] = field(default_factory=dict)


@dataclass(frozen=True)
class SituationalPolicy:
    branches: tuple[SituationalBranch, ...]
    abstentions: tuple[str, ...]


@dataclass(frozen=True)
class HeroBuildEvidence:
    hero_id: int
    hero: str
    eligible_player_matches: int
    selection_eligible_player_matches: int
    fold_eligible_player_matches: dict[str, int]
    median_final_net_worth: int | None
    items: tuple[ItemEvidence, ...]
    core_policy: CorePolicyEvidence
    tier_policy: TierPolicyEvidence
    sequence_policy: SequencePolicy | None = None
    situational_policy: SituationalPolicy | None = None
    path_id: str = "default"
    path_label: str = "Evidence Default"
    signature_item_ids: tuple[int, ...] = ()
    discovery: dict[str, object] = field(default_factory=dict)
    purchase_timing: tuple[PurchaseTiming, ...] = ()
    automatic_branches: tuple[AutomaticBranch, ...] = ()
    cohort: HeroCohort | None = None


@dataclass(frozen=True)
class SelectedHeroBuild:
    hero_id: int
    path_id: str
    path_label: str
    signature_item_ids: tuple[int, ...]
    core: tuple[ItemEvidence, ...]
    core_purchase_path: tuple[ItemEvidence, ...]
    tiers: dict[int, tuple[ItemEvidence, ...]]
    backbone: tuple[ItemEvidence, ...]
    optional_core: tuple[ItemEvidence, ...]
    core_alternatives: tuple[CoreAlternativeEvidence, ...]
    backbone_matches: int
    backbone_share: float
    core_joint_matches: int
    core_joint_share: float
    median_final_net_worth: int | None
    core_target_cost: int
    evidence_summary: dict[str, object] = field(default_factory=dict)
    purchase_timing: tuple[PurchaseTiming, ...] = ()
    automatic_branches: tuple[AutomaticBranch, ...] = ()
    cohort: HeroCohort | None = None


@dataclass(frozen=True)
class BuildEvidenceCatalog:
    artifact_id: str
    client_version: int
    patch: dict[str, object]
    cohort: dict[str, object]
    epochs: EpochSet
    rank_labels_sha256: str
    heroes_sha256: str
    items_sha256: str
    requested_hero_ids: frozenset[int]
    heroes: dict[int, HeroBuildEvidence]
    raw_bytes: bytes
    exclusions: dict[int, str] = field(default_factory=dict)
    assets: tuple[dict[str, object], ...] = ()
    hero_builds: dict[int, tuple[HeroBuildEvidence, ...]] = field(default_factory=dict)

    @property
    def as_of_timestamp(self) -> int:
        value = self.cohort.get("as_of")
        if not isinstance(value, str):
            raise ArtifactError("build evidence has no frozen as-of timestamp")
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as error:
            raise ArtifactError(
                "build evidence has an invalid as-of timestamp"
            ) from error
        if parsed.tzinfo is None:
            raise ArtifactError("build evidence as-of timestamp lacks a timezone")
        return int(parsed.timestamp())


def nondecreasing_window_schedule(
    path: Sequence[int],
    bounds: Mapping[int, tuple[float, float]],
) -> tuple[float, ...] | None:
    """Return the earliest feasible checkpoints through reliable observed IQRs.

    A missing interval gives no route constraint. Every supplied interval must be
    finite, and one nondecreasing checkpoint sequence must pass through all supplied
    intervals. This keeps unreliable timing out of route selection.

    Returns:
        The earliest feasible checkpoint per purchase, or ``None``.

    """
    current = 0.0
    schedule: list[float] = []
    for item_id in path:
        window = bounds.get(item_id)
        if window is None:
            schedule.append(current)
            continue
        lower, upper = window
        if not math.isfinite(lower) or not math.isfinite(upper) or lower > upper:
            return None
        current = max(current, lower)
        if current > upper:
            return None
        schedule.append(current)
    return tuple(schedule)
