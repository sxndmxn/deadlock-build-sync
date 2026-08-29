from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, cast

from .artifacts import ArtifactError
from .mechanics import (
    InventoryState,
    ItemGraph,
    MechanicsError,
    purchase_item,
    schedule_component_path,
)
from .snapshot import EpochBoundary, EpochSet, MatchMode, sha256_json

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    from .ranks import RankCatalog, RankRange

BUILD_EVIDENCE_SCHEMA_VERSION = 8

type _SequencePolicyDocument = dict[str, Any]
type _SituationalBranchDocument = dict[str, Any]
type _SituationalPolicyDocument = dict[str, Any]


MAXIMUM_CORE_ITEM_COUNT = 9
TIER_ITEM_COUNT = 10
MINIMUM_TIER_SUPPORT = 20
MINIMUM_TIER_ADOPTION = 0.05
MAXIMUM_TIER_ADOPTION_DRIFT = 0.10
MINIMUM_PURCHASE_WINDOW_COVERAGE = 0.50
MINIMUM_PURCHASE_WINDOW_OBSERVATIONS = 20
MINIMUM_CORE_SUPPORT = 20
METHOD_VERSION = "state-aware-multi-path-v7"
SEQUENCE_POLICY_VERSION = 3
SITUATIONAL_POLICY_VERSION = 2
CORE_POLICY_VERSION = 3
TIER_POLICY_VERSION = 1
MINIMUM_BACKBONE_ITEM_COUNT = 4
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
        or lower is None
        or upper is None
        or train_lower is None
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
class CoreAlternativeEvidence:
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
    vs: str
    why: str
    swap: str
    when: str
    skip: str
    mechanics_refs: tuple[str, ...]
    comparator_mechanics_refs: tuple[str, ...]
    fold_estimates: dict[str, float]
    fold_diagnostics: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass(frozen=True)
class CorePolicyEvidence:
    backbone_item_ids: tuple[int, ...]
    default_item_ids: tuple[int, ...]
    backbone_matches: int
    backbone_fold_matches: dict[str, int]
    default_matches: int
    alternatives: tuple[CoreAlternativeEvidence, ...]
    candidate_audit: tuple[dict[str, Any], ...]
    evaluation: dict[str, Any]
    default_fold_matches: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class TierPolicyEvidence:
    item_ids_by_tier: dict[int, tuple[int, ...]]


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
    evaluation: dict[str, Any]


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
    median_final_net_worth: int
    items: tuple[ItemEvidence, ...]
    core_policy: CorePolicyEvidence
    tier_policy: TierPolicyEvidence
    sequence_policy: SequencePolicy | None = None
    situational_policy: SituationalPolicy | None = None
    path_id: str = "default"
    path_label: str = "Evidence Default"
    signature_item_ids: tuple[int, ...] = ()
    discovery: dict[str, Any] = field(default_factory=dict)


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
    median_final_net_worth: int
    core_target_cost: int


@dataclass(frozen=True)
class BuildEvidenceCatalog:
    artifact_id: str
    client_version: int
    patch: dict[str, Any]
    cohort: dict[str, Any]
    epochs: EpochSet
    rank_labels_sha256: str
    heroes_sha256: str
    items_sha256: str
    requested_hero_ids: frozenset[int]
    heroes: dict[int, HeroBuildEvidence]
    raw_bytes: bytes
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


def _required_int(
    value: object,
    label: str,
    *,
    minimum: int = 0,
    maximum: int | None = None,
) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < minimum
        or (maximum is not None and value > maximum)
    ):
        raise ArtifactError(f"build evidence has invalid {label}")
    return value


def _required_float(
    value: object, label: str, *, minimum: float = 0.0, maximum: float | None = None
) -> float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
        or float(value) < minimum
        or (maximum is not None and float(value) > maximum)
    ):
        raise ArtifactError(f"build evidence has invalid {label}")
    return float(value)


def _finite_float(value: object, label: str) -> float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
    ):
        raise ArtifactError(f"build evidence has invalid {label}")
    return float(value)


def _required_bool(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise ArtifactError(f"build evidence has invalid {label}")
    return value


def _optional_float(value: object, label: str) -> float | None:
    return None if value is None else _required_float(value, label)


def _required_sha256(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ArtifactError(f"build evidence has invalid {label}")
    return value


def _document(value: object, error_message: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ArtifactError(error_message)
    return cast("dict[str, Any]", value)


def _item(value: object, hero_id: int) -> ItemEvidence:  # ruff: ignore[too-many-statements]
    if not isinstance(value, dict):
        raise ArtifactError(f"hero {hero_id} has a malformed item evidence row")
    item_id = _required_int(value.get("item_id"), "item id", minimum=1)
    name = value.get("item")
    slot = value.get("slot")
    if (
        not isinstance(name, str)
        or not name.strip()
        or not isinstance(slot, str)
        or not slot.strip()
    ):
        raise ArtifactError(f"hero {hero_id} item {item_id} lacks identity")
    adopter_matches = _required_int(value.get("adopter_matches"), "adopter matches")
    eligible = _required_int(
        value.get("eligible_player_matches"), "eligible player matches", minimum=1
    )
    purchase_events = _required_int(value.get("purchase_events"), "purchase events")
    wins = _required_int(value.get("wins"), "wins")
    if (
        adopter_matches > eligible
        or purchase_events < adopter_matches
        or wins > adopter_matches
    ):
        raise ArtifactError(f"hero {hero_id} item {item_id} has impossible counts")
    adoption = _required_float(value.get("adoption"), "adoption", maximum=1.0)
    outcome = _required_float(
        value.get("observed_outcome_rate"), "observed outcome", maximum=1.0
    )
    if not math.isclose(adoption, adopter_matches / eligible, abs_tol=1e-9):
        raise ArtifactError(f"hero {hero_id} item {item_id} adoption is inconsistent")
    expected_outcome = wins / adopter_matches if adopter_matches else 0.0
    if not math.isclose(outcome, expected_outcome, abs_tol=1e-9):
        raise ArtifactError(f"hero {hero_id} item {item_id} outcome is inconsistent")
    tier = _required_int(value.get("tier"), "item tier", minimum=1)
    if tier > 4:
        raise ArtifactError(f"hero {hero_id} item {item_id} has invalid tier")
    median_net_worth = _optional_float(
        value.get("median_valid_buy_net_worth"), "median buy net worth"
    )
    q25 = _optional_float(value.get("buy_net_worth_q25"), "buy net worth q25")
    q75 = _optional_float(value.get("buy_net_worth_q75"), "buy net worth q75")
    if (
        (median_net_worth is None) != (q25 is None)
        or (median_net_worth is None) != (q75 is None)
        or (
            median_net_worth is not None
            and q25 is not None
            and q75 is not None
            and not q25 <= median_net_worth <= q75
        )
    ):
        raise ArtifactError(
            f"hero {hero_id} item {item_id} has invalid net-worth quantiles"
        )
    fold_counts = {
        fold: (
            _required_int(
                value.get(f"{fold}_adopter_matches"),
                f"{fold} adopter matches",
            ),
            _required_int(
                value.get(f"{fold}_eligible_player_matches"),
                f"{fold} eligible player matches",
                minimum=0 if fold == "test" else 1,
            ),
        )
        for fold in ("training", "validation", "test")
    }
    fold_adoption = {
        fold: _required_float(
            value.get(f"{fold}_adoption"),
            f"{fold} adoption",
            maximum=1.0,
        )
        for fold in fold_counts
    }
    if any(
        adopters > fold_eligible
        or not math.isclose(
            fold_adoption[fold],
            adopters / fold_eligible if fold_eligible else 0.0,
            abs_tol=1e-9,
        )
        for fold, (adopters, fold_eligible) in fold_counts.items()
    ):
        raise ArtifactError(f"hero {hero_id} item {item_id} has invalid fold counts")
    selection_adopters = _required_int(
        value.get("selection_adopter_matches"), "selection adopter matches"
    )
    selection_eligible = _required_int(
        value.get("selection_eligible_player_matches"),
        "selection eligible player matches",
        minimum=1,
    )
    selection_adoption = _required_float(
        value.get("selection_adoption"), "selection adoption", maximum=1.0
    )
    if (
        selection_adopters != fold_counts["training"][0] + fold_counts["validation"][0]
        or selection_eligible
        != fold_counts["training"][1] + fold_counts["validation"][1]
        or adopter_matches != selection_adopters + fold_counts["test"][0]
        or eligible != selection_eligible + fold_counts["test"][1]
        or not math.isclose(
            selection_adoption,
            selection_adopters / selection_eligible,
            abs_tol=1e-9,
        )
    ):
        raise ArtifactError(
            f"hero {hero_id} item {item_id} has inconsistent selection counts"
        )
    selection_buy_time = _optional_float(
        value.get("selection_median_buy_time_s"), "selection median buy time"
    )
    selection_median_net_worth = _optional_float(
        value.get("selection_median_valid_buy_net_worth"),
        "selection median buy net worth",
    )
    selection_q25 = _optional_float(
        value.get("selection_buy_net_worth_q25"),
        "selection buy net worth q25",
    )
    selection_q75 = _optional_float(
        value.get("selection_buy_net_worth_q75"),
        "selection buy net worth q75",
    )
    selection_valid_observations = _required_int(
        value.get("selection_valid_buy_net_worth_observations"),
        "selection valid buy net worth observations",
    )
    selection_valid_share = _required_float(
        value.get("selection_valid_buy_net_worth_share"),
        "selection valid buy net worth share",
        maximum=1.0,
    )
    if (
        (selection_buy_time is None) != (selection_adopters == 0)
        or selection_valid_observations > selection_adopters
        or not math.isclose(
            selection_valid_share,
            selection_valid_observations / selection_adopters
            if selection_adopters
            else 0.0,
            abs_tol=1e-9,
        )
        or (selection_median_net_worth is None) != (selection_valid_observations == 0)
        or (selection_q25 is None) != (selection_valid_observations == 0)
        or (selection_q75 is None) != (selection_valid_observations == 0)
        or (
            selection_median_net_worth is not None
            and selection_q25 is not None
            and selection_q75 is not None
            and not selection_q25 <= selection_median_net_worth <= selection_q75
        )
    ):
        raise ArtifactError(
            f"hero {hero_id} item {item_id} has invalid selection timing evidence"
        )
    fold_window_evidence: dict[str, tuple[int, float | None, float | None]] = {}
    for fold in ("training", "validation"):
        observations = _required_int(
            value.get(f"{fold}_valid_buy_net_worth_observations"),
            f"{fold} valid buy net worth observations",
        )
        lower = _optional_float(
            value.get(f"{fold}_buy_net_worth_q25"),
            f"{fold} buy net worth q25",
        )
        upper = _optional_float(
            value.get(f"{fold}_buy_net_worth_q75"),
            f"{fold} buy net worth q75",
        )
        if (
            observations > fold_counts[fold][0]
            or (lower is None) != (observations == 0)
            or (upper is None) != (observations == 0)
            or (lower is not None and upper is not None and lower > upper)
        ):
            raise ArtifactError(
                f"hero {hero_id} item {item_id} has invalid {fold} window evidence"
            )
        fold_window_evidence[fold] = observations, lower, upper
    if selection_valid_observations != sum(
        row[0] for row in fold_window_evidence.values()
    ):
        raise ArtifactError(
            f"hero {hero_id} item {item_id} has inconsistent window counts"
        )
    raw_imbue_target_id = value.get("imbue_target_ability_id")
    imbue_target_id = (
        None
        if raw_imbue_target_id is None
        else _required_int(raw_imbue_target_id, "imbue target ability id", minimum=1)
    )
    imbue_target = value.get("imbue_target_ability")
    imbue_target_matches = _required_int(
        value.get("imbue_target_matches"), "imbue target matches"
    )
    imbue_observations = _required_int(
        value.get("imbue_observations"), "imbue observations"
    )
    imbue_target_share = _required_float(
        value.get("imbue_target_share"), "imbue target share", maximum=1.0
    )
    if (
        imbue_target_matches > imbue_observations
        or (imbue_target_id is None) != (imbue_target is None)
        or (
            imbue_target_id is None
            and any((imbue_target_matches, imbue_observations, imbue_target_share))
        )
        or (
            imbue_target_id is not None
            and (
                not isinstance(imbue_target, str)
                or not imbue_target.strip()
                or imbue_target_matches < MINIMUM_IMBUE_SUPPORT
                or imbue_target_share <= MINIMUM_IMBUE_SHARE
                or not math.isclose(
                    imbue_target_share,
                    imbue_target_matches / imbue_observations,
                    abs_tol=1e-9,
                )
            )
        )
    ):
        raise ArtifactError(f"hero {hero_id} item {item_id} has invalid imbue evidence")
    return ItemEvidence(
        item_id=item_id,
        item=name.strip(),
        tier=tier,
        cost=_required_int(value.get("cost"), "item cost"),
        slot=slot.strip().casefold(),
        active=_required_bool(value.get("active"), "active-item flag"),
        adopter_matches=adopter_matches,
        eligible_player_matches=eligible,
        purchase_events=purchase_events,
        wins=wins,
        adoption=adoption,
        observed_outcome_rate=outcome,
        median_buy_time_s=_required_float(
            value.get("median_buy_time_s"), "median buy time"
        ),
        median_valid_buy_net_worth=median_net_worth,
        buy_net_worth_q25=q25,
        buy_net_worth_q75=q75,
        valid_buy_net_worth_share=_required_float(
            value.get("valid_buy_net_worth_share"),
            "valid buy net worth share",
            maximum=1.0,
        ),
        selection_adopter_matches=selection_adopters,
        selection_eligible_player_matches=selection_eligible,
        training_adopter_matches=fold_counts["training"][0],
        training_eligible_player_matches=fold_counts["training"][1],
        validation_adopter_matches=fold_counts["validation"][0],
        validation_eligible_player_matches=fold_counts["validation"][1],
        test_adopter_matches=fold_counts["test"][0],
        test_eligible_player_matches=fold_counts["test"][1],
        selection_adoption=selection_adoption,
        training_adoption=fold_adoption["training"],
        validation_adoption=fold_adoption["validation"],
        test_adoption=fold_adoption["test"],
        selection_median_buy_time_s=selection_buy_time,
        selection_median_valid_buy_net_worth=selection_median_net_worth,
        selection_buy_net_worth_q25=selection_q25,
        selection_buy_net_worth_q75=selection_q75,
        selection_valid_buy_net_worth_share=selection_valid_share,
        selection_valid_buy_net_worth_observations=selection_valid_observations,
        training_valid_buy_net_worth_observations=fold_window_evidence["training"][0],
        validation_valid_buy_net_worth_observations=fold_window_evidence["validation"][
            0
        ],
        training_buy_net_worth_q25=fold_window_evidence["training"][1],
        training_buy_net_worth_q75=fold_window_evidence["training"][2],
        validation_buy_net_worth_q25=fold_window_evidence["validation"][1],
        validation_buy_net_worth_q75=fold_window_evidence["validation"][2],
        imbue_target_ability_id=imbue_target_id,
        imbue_target_ability=(
            str(imbue_target).strip() if isinstance(imbue_target, str) else None
        ),
        imbue_target_matches=imbue_target_matches,
        imbue_observations=imbue_observations,
        imbue_target_share=imbue_target_share,
    )


def _sequence_transition(value: object, hero_id: int) -> SequenceTransition:
    if not isinstance(value, dict):
        raise ArtifactError(f"hero {hero_id} has a malformed sequence transition")
    level = value.get("level")
    if level not in SEQUENCE_LEVELS:
        raise ArtifactError(f"hero {hero_id} has an invalid sequence backoff level")
    support = _required_int(value.get("support"), "transition support", minimum=1)
    context_support = _required_int(
        value.get("context_support"),
        "transition context support",
        minimum=support,
    )
    return SequenceTransition(
        level=str(level),
        first_item_id=_required_int(value.get("first_item_id"), "first item id"),
        previous_item_id=_required_int(
            value.get("previous_item_id"), "previous item id"
        ),
        position=_required_int(value.get("position"), "purchase position"),
        next_item_id=_required_int(
            value.get("next_item_id"), "next item id", minimum=1
        ),
        support=support,
        context_support=context_support,
    )


def _sequence_policy(value: object, hero_id: int) -> SequencePolicy:
    if not isinstance(value, dict) or value.get("version") != SEQUENCE_POLICY_VERSION:
        raise ArtifactError(f"hero {hero_id} has no supported sequence policy")
    data = cast("_SequencePolicyDocument", value)
    raw_path = data.get("component_expanded_default_path")
    raw_transitions = data.get("transitions")
    evaluation = data.get("evaluation")
    production_model = data.get("production_model")
    if (
        not isinstance(raw_path, list)
        or not raw_path
        or not isinstance(raw_transitions, list)
        or not raw_transitions
        or not isinstance(evaluation, dict)
        or production_model != "deterministic_backoff"
    ):
        raise ArtifactError(f"hero {hero_id} has an incomplete sequence policy")
    path = tuple(
        _required_int(item_id, "default path item id", minimum=1)
        for item_id in raw_path
    )
    if len(path) != len(set(path)):
        raise ArtifactError(f"hero {hero_id} default path repeats an item")
    minimum_support = _required_int(
        data.get("minimum_support"), "sequence minimum support", minimum=20
    )
    transitions = tuple(_sequence_transition(row, hero_id) for row in raw_transitions)
    if any(row.support < minimum_support for row in transitions):
        raise ArtifactError(f"hero {hero_id} has a weak sequence transition")
    return SequencePolicy(
        path,
        transitions,
        minimum_support,
        str(production_model),
        evaluation,
    )


def _situational_branch(value: object, hero_id: int) -> SituationalBranch:
    if not isinstance(value, dict):
        raise ArtifactError(f"hero {hero_id} has a malformed situational branch")
    data = cast("_SituationalBranchDocument", value)
    threat = data.get("threat")
    enemy_hero_id = data.get("enemy_hero_id")
    enemy_scope = data.get("enemy_scope")
    text_fields = (
        "mechanic_ref",
        "comparator",
        "trigger",
        "replacement",
        "execution",
        "failure_condition",
    )
    if (
        threat not in THREAT_CLASSES
        or enemy_scope not in {"same_lane", "whole_enemy_team"}
        or any(
            not isinstance(data.get(field), str) or not str(data[field]).strip()
            for field in text_fields
        )
    ):
        raise ArtifactError(f"hero {hero_id} has an incomplete situational branch")
    if enemy_hero_id is not None:
        enemy_hero_id = _required_int(enemy_hero_id, "enemy hero id", minimum=1)
    item_id = _required_int(data.get("item_id"), "situational item id", minimum=1)
    comparator_item_id = _required_int(
        data.get("comparator_item_id"),
        "situational comparator item id",
        minimum=1,
    )
    if comparator_item_id == item_id:
        raise ArtifactError(f"hero {hero_id} compares a situational item with itself")
    if not str(data["mechanic_ref"]).startswith(f"item/{item_id}/"):
        raise ArtifactError(
            f"hero {hero_id} has a mismatched situational mechanic reference"
        )
    raw_enemy_refs = data.get("enemy_mechanics_refs")
    if (
        not isinstance(raw_enemy_refs, list)
        or not raw_enemy_refs
        or not all(isinstance(ref, str) and ref.strip() for ref in raw_enemy_refs)
    ):
        raise ArtifactError(
            f"hero {hero_id} situational branch lacks enemy mechanics refs"
        )
    same_opportunity = _required_bool(
        data.get("same_opportunity"), "situational same-opportunity gate"
    )
    comparison_support = _required_int(
        data.get("comparison_support"),
        "situational comparison support",
        minimum=20,
    )
    support = _required_int(data.get("support"), "situational support", minimum=20)
    effective = _required_float(
        data.get("effective_support"), "situational effective support", minimum=20
    )
    overlap = _required_float(data.get("overlap"), "situational overlap", maximum=1.0)
    stable = _required_bool(data.get("stable"), "situational stability")
    raw_interval = data.get("comparative_interval")
    if not isinstance(raw_interval, list) or len(raw_interval) != 2:
        raise ArtifactError(
            f"hero {hero_id} has no bounded situational comparative interval"
        )
    lower = _required_float(raw_interval[0], "situational interval lower")
    upper = _required_float(raw_interval[1], "situational interval upper")
    if lower > upper or lower <= 0 or upper - lower > MAX_COMPARATIVE_INTERVAL_WIDTH:
        raise ArtifactError(
            f"hero {hero_id} has an unqualified situational comparative interval"
        )
    if overlap < 0.5 or not stable or not same_opportunity:
        raise ArtifactError(
            f"hero {hero_id} contains an unqualified situational branch"
        )
    raw_fold_estimates = data.get("fold_comparative_estimates")
    raw_fold_support = data.get("fold_support")
    if (
        not isinstance(raw_fold_estimates, dict)
        or not isinstance(raw_fold_support, dict)
        or not {"train", "validation", "test"} <= set(raw_fold_estimates)
        or not {"train", "validation", "test"} <= set(raw_fold_support)
    ):
        raise ArtifactError(f"hero {hero_id} lacks situational fold evidence")
    fold_estimates = {
        fold: _finite_float(estimate, f"situational {fold} comparative estimate")
        for fold, estimate in raw_fold_estimates.items()
    }
    fold_support: dict[str, dict[str, int]] = {}
    for fold in ("train", "validation", "test"):
        support_document = _document(
            raw_fold_support[fold],
            f"hero {hero_id} lacks situational {fold} support",
        )
        fold_support[fold] = {
            side: _required_int(
                support_document.get(side),
                f"situational {fold} {side} support",
                minimum=20,
            )
            for side in ("item", "comparator")
        }
    if (
        fold_estimates["train"] <= 0
        or fold_estimates["validation"] <= 0
        or fold_estimates["test"] <= 0
        or abs(fold_estimates["train"] - fold_estimates["validation"]) > 0.05
    ):
        raise ArtifactError(f"hero {hero_id} has unstable situational fold evidence")
    return SituationalBranch(
        threat=str(threat),
        item_id=item_id,
        enemy_hero_id=enemy_hero_id,
        enemy_scope=str(enemy_scope),
        phase=_required_int(data.get("phase"), "situational phase", maximum=3),
        tier=_required_int(
            data.get("tier"), "situational decision tier", minimum=1, maximum=4
        ),
        mechanic_ref=str(data["mechanic_ref"]),
        enemy_mechanics_refs=tuple(str(ref).strip() for ref in raw_enemy_refs),
        fold_comparative_estimates=fold_estimates,
        fold_support=fold_support,
        comparator=str(data["comparator"]),
        comparator_item_id=comparator_item_id,
        comparison_support=comparison_support,
        same_opportunity=same_opportunity,
        support=support,
        effective_support=effective,
        overlap=overlap,
        stable=stable,
        comparative_interval=(lower, upper),
        trigger=str(data["trigger"]),
        replacement=str(data["replacement"]),
        execution=str(data["execution"]),
        failure_condition=str(data["failure_condition"]),
    )


def _situational_policy(value: object, hero_id: int) -> SituationalPolicy:
    if (
        not isinstance(value, dict)
        or value.get("version") != SITUATIONAL_POLICY_VERSION
    ):
        raise ArtifactError(f"hero {hero_id} has no supported situational policy")
    data = cast("_SituationalPolicyDocument", value)
    branches = data.get("branches")
    abstentions = data.get("abstentions")
    vocabulary = data.get("threat_vocabulary")
    if (
        not isinstance(branches, list)
        or not isinstance(abstentions, list)
        or vocabulary != sorted(THREAT_CLASSES)
    ):
        raise ArtifactError(f"hero {hero_id} has an incomplete situational policy")
    if len(branches) > MAX_SITUATIONAL_BRANCHES:
        raise ArtifactError(f"hero {hero_id} has too many situational branches")
    if not all(isinstance(reason, str) and reason.strip() for reason in abstentions):
        raise ArtifactError(f"hero {hero_id} has an invalid situational abstention")
    admitted = tuple(_situational_branch(row, hero_id) for row in branches)
    identities = [
        (branch.threat, branch.enemy_hero_id, branch.item_id) for branch in admitted
    ]
    if len(identities) != len(set(identities)):
        raise ArtifactError(f"hero {hero_id} has duplicate situational branches")
    item_ids = [branch.item_id for branch in admitted]
    if len(item_ids) != len(set(item_ids)):
        raise ArtifactError(f"hero {hero_id} repeats a situational item")
    if not admitted and not abstentions:
        raise ArtifactError(f"hero {hero_id} has no situational result")
    return SituationalPolicy(
        admitted,
        tuple(cast("list[str]", abstentions)),
    )


def _hero_items(
    raw_items: Sequence[object],
    hero_id: int,
    eligible: int,
) -> tuple[tuple[ItemEvidence, ...], list[int]]:
    items = tuple(_item(row, hero_id) for row in raw_items)
    item_ids = [item.item_id for item in items]
    if len(item_ids) != len(set(item_ids)):
        raise ArtifactError(f"hero {hero_id} has duplicate item evidence")
    if any(item.eligible_player_matches != eligible for item in items):
        raise ArtifactError(f"hero {hero_id} item denominators disagree")
    return items, item_ids


def _core_alternative_interval(
    document: dict[str, Any], hero_id: int
) -> tuple[float, float, float]:
    raw_interval = document.get("comparative_interval")
    if not isinstance(raw_interval, list) or len(raw_interval) != 2:
        raise ArtifactError(f"hero {hero_id} core alternative lacks a DR interval")
    lower = _finite_float(raw_interval[0], "core alternative interval lower")
    upper = _finite_float(raw_interval[1], "core alternative interval upper")
    estimate = _finite_float(
        document.get("dr_estimate"), "core alternative DR estimate"
    )
    if (
        lower > upper
        or not lower <= estimate <= upper
        or lower <= 0
        or upper - lower > MAX_COMPARATIVE_INTERVAL_WIDTH
    ):
        raise ArtifactError(f"hero {hero_id} has an invalid core alternative interval")
    return lower, upper, estimate


def _core_alternative(
    value: object,
    hero_id: int,
    item_ids: set[int],
    default_item_ids: set[int],
) -> CoreAlternativeEvidence:
    document = _document(value, f"hero {hero_id} has a malformed core alternative")
    item_id = _required_int(
        document.get("item_id"), "core alternative item id", minimum=1
    )
    comparator_id = _required_int(
        document.get("comparator_item_id"),
        "core alternative comparator item id",
        minimum=1,
    )
    if (
        item_id not in item_ids
        or item_id in default_item_ids
        or comparator_id not in default_item_ids
    ):
        raise ArtifactError(f"hero {hero_id} has an invalid core alternative pair")
    text_fields = ("vs", "why", "swap", "when", "skip")
    if any(
        not isinstance(document.get(field), str) or not str(document[field]).strip()
        for field in text_fields
    ):
        raise ArtifactError(f"hero {hero_id} has an incomplete core alternative")
    raw_refs = document.get("mechanics_refs")
    raw_comparator_refs = document.get("comparator_mechanics_refs")
    if (
        not isinstance(raw_refs, list)
        or not raw_refs
        or not all(isinstance(ref, str) and ref.strip() for ref in raw_refs)
        or not isinstance(raw_comparator_refs, list)
        or not raw_comparator_refs
        or not all(isinstance(ref, str) and ref.strip() for ref in raw_comparator_refs)
    ):
        raise ArtifactError(f"hero {hero_id} core alternative lacks mechanics refs")
    lower, upper, estimate = _core_alternative_interval(document, hero_id)
    fold_estimates = document.get("fold_estimates")
    if not isinstance(fold_estimates, dict) or not {
        "train",
        "validation",
    } <= set(fold_estimates):
        raise ArtifactError(f"hero {hero_id} core alternative lacks temporal estimates")
    fold_document = _document(
        fold_estimates,
        f"hero {hero_id} core alternative lacks temporal estimates",
    )
    parsed_folds = {
        fold: _finite_float(fold_document[fold], f"core alternative {fold} estimate")
        for fold in fold_document
    }
    raw_fold_diagnostics = document.get("fold_diagnostics")
    if not isinstance(raw_fold_diagnostics, dict) or not {
        "train",
        "validation",
    } <= set(raw_fold_diagnostics):
        raise ArtifactError(f"hero {hero_id} core alternative lacks fold diagnostics")
    parsed_fold_diagnostics: dict[str, dict[str, Any]] = {}
    for fold in ("train", "validation"):
        diagnostics = _document(
            raw_fold_diagnostics[fold],
            f"hero {hero_id} core alternative lacks {fold} diagnostics",
        )
        raw_fold_interval = diagnostics.get("interval")
        if not isinstance(raw_fold_interval, list) or len(raw_fold_interval) != 2:
            raise ArtifactError(
                f"hero {hero_id} core alternative lacks a {fold} interval"
            )
        fold_lower = _finite_float(
            raw_fold_interval[0], f"core alternative {fold} interval lower"
        )
        fold_upper = _finite_float(
            raw_fold_interval[1], f"core alternative {fold} interval upper"
        )
        fold_estimate = _finite_float(
            diagnostics.get("estimate"), f"core alternative {fold} estimate"
        )
        fold_support = _required_int(
            diagnostics.get("support"),
            f"core alternative {fold} support",
            minimum=MINIMUM_CORE_SUPPORT,
        )
        fold_comparison_support = _required_int(
            diagnostics.get("comparison_support"),
            f"core alternative {fold} comparison support",
            minimum=MINIMUM_CORE_SUPPORT,
        )
        fold_effective_support = _required_float(
            diagnostics.get("effective_support"),
            f"core alternative {fold} effective support",
            minimum=MINIMUM_CORE_SUPPORT,
        )
        fold_overlap = _required_float(
            diagnostics.get("overlap"),
            f"core alternative {fold} overlap",
            maximum=1.0,
        )
        fold_smd = _required_float(
            diagnostics.get("maximum_standardized_mean_difference"),
            f"core alternative {fold} balance",
        )
        if (
            fold_lower <= 0
            or fold_lower > fold_upper
            or not fold_lower <= fold_estimate <= fold_upper
            or fold_upper - fold_lower > MAX_COMPARATIVE_INTERVAL_WIDTH
            or fold_overlap < 0.5
            or fold_smd > 0.1
            or not math.isclose(parsed_folds[fold], fold_estimate, abs_tol=1e-12)
        ):
            raise ArtifactError(
                f"hero {hero_id} contains an unqualified {fold} core alternative"
            )
        parsed_fold_diagnostics[fold] = {
            **diagnostics,
            "support": fold_support,
            "comparison_support": fold_comparison_support,
            "effective_support": fold_effective_support,
            "overlap": fold_overlap,
            "maximum_standardized_mean_difference": fold_smd,
            "estimate": fold_estimate,
            "interval": [fold_lower, fold_upper],
        }
    if abs(parsed_folds["train"] - parsed_folds["validation"]) > 0.05:
        raise ArtifactError(f"hero {hero_id} has an unstable core alternative")
    effective_support = _required_float(
        document.get("effective_support"),
        "core alternative effective support",
        minimum=MINIMUM_CORE_SUPPORT,
    )
    overlap = _required_float(
        document.get("overlap"), "core alternative overlap", maximum=1.0
    )
    stable = _required_bool(document.get("stable"), "core alternative stability")
    if overlap < 0.5 or not stable:
        raise ArtifactError(f"hero {hero_id} contains an unqualified core alternative")
    return CoreAlternativeEvidence(
        item_id=item_id,
        comparator_item_id=comparator_id,
        stage=_required_int(document.get("stage"), "core alternative stage", minimum=1),
        support=_required_int(
            document.get("support"),
            "core alternative support",
            minimum=MINIMUM_CORE_SUPPORT,
        ),
        comparison_support=_required_int(
            document.get("comparison_support"),
            "core alternative comparison support",
            minimum=MINIMUM_CORE_SUPPORT,
        ),
        effective_support=effective_support,
        overlap=overlap,
        stable=stable,
        dr_estimate=estimate,
        comparative_interval=(lower, upper),
        vs=str(document["vs"]).strip(),
        why=str(document["why"]).strip(),
        swap=str(document["swap"]).strip(),
        when=str(document["when"]).strip(),
        skip=str(document["skip"]).strip(),
        mechanics_refs=tuple(str(ref).strip() for ref in raw_refs),
        comparator_mechanics_refs=tuple(
            str(ref).strip() for ref in raw_comparator_refs
        ),
        fold_estimates=parsed_folds,
        fold_diagnostics=parsed_fold_diagnostics,
    )


def _core_policy(
    value: object,
    hero_id: int,
    item_ids: set[int],
    eligible: int,
) -> CorePolicyEvidence:
    if not isinstance(value, dict) or value.get("version") != CORE_POLICY_VERSION:
        raise ArtifactError(f"hero {hero_id} has no supported core policy")
    raw_backbone = value.get("backbone_item_ids")
    raw_default = value.get("default_item_ids")
    raw_alternatives = value.get("alternatives")
    raw_fold_matches = value.get("backbone_fold_matches")
    raw_default_fold_matches = value.get("default_fold_matches")
    candidate_audit = value.get("candidate_audit")
    evaluation = value.get("evaluation")
    if (
        not isinstance(raw_backbone, list)
        or not isinstance(raw_default, list)
        or not isinstance(raw_alternatives, list)
        or not isinstance(raw_fold_matches, dict)
        or not isinstance(raw_default_fold_matches, dict)
        or not isinstance(candidate_audit, list)
        or not isinstance(evaluation, dict)
    ):
        raise ArtifactError(f"hero {hero_id} has an incomplete core policy")
    if any(not isinstance(row, dict) for row in candidate_audit):
        raise ArtifactError(f"hero {hero_id} has a malformed core candidate audit")
    backbone = tuple(
        _required_int(item_id, "backbone item id", minimum=1)
        for item_id in raw_backbone
    )
    default = tuple(
        _required_int(item_id, "default core item id", minimum=1)
        for item_id in raw_default
    )
    if (
        not MINIMUM_BACKBONE_ITEM_COUNT <= len(backbone) <= MAXIMUM_BACKBONE_ITEM_COUNT
        or len(backbone) != len(set(backbone))
        or not len(backbone) <= len(default) <= MAXIMUM_CORE_ITEM_COUNT
        or len(default) != len(set(default))
        or not set(backbone) <= set(default) <= item_ids
    ):
        raise ArtifactError(f"hero {hero_id} has invalid core policy membership")
    fold_matches = {
        fold: _required_int(
            raw_fold_matches.get(fold),
            f"{fold} backbone support",
            minimum=0 if fold == "test" else MINIMUM_CORE_SUPPORT,
        )
        for fold in ("train", "validation", "test")
    }
    backbone_matches = _required_int(
        value.get("backbone_matches"),
        "backbone support",
        minimum=fold_matches["train"] + fold_matches["validation"],
    )
    if (
        backbone_matches != fold_matches["train"] + fold_matches["validation"]
        or backbone_matches > eligible
    ):
        raise ArtifactError(f"hero {hero_id} backbone support exceeds its cohort")
    alternatives = tuple(
        _core_alternative(row, hero_id, item_ids, set(default))
        for row in raw_alternatives
    )
    if (
        len(alternatives) > MAXIMUM_CORE_ALTERNATIVES
        or len({alternative.item_id for alternative in alternatives})
        != len(alternatives)
        or any(alternative.stage > len(default) for alternative in alternatives)
    ):
        raise ArtifactError(f"hero {hero_id} has invalid core alternatives")
    default_matches = _required_int(value.get("default_matches"), "default support")
    default_fold_matches = {
        fold: _required_int(
            raw_default_fold_matches.get(fold),
            f"{fold} default support",
            minimum=0 if fold == "test" else MINIMUM_CORE_SUPPORT,
        )
        for fold in ("train", "validation", "test")
    }
    if (
        default_matches
        != default_fold_matches["train"] + default_fold_matches["validation"]
        or default_matches > eligible
    ):
        raise ArtifactError(f"hero {hero_id} default support exceeds its cohort")
    return CorePolicyEvidence(
        backbone_item_ids=backbone,
        default_item_ids=default,
        backbone_matches=backbone_matches,
        backbone_fold_matches=fold_matches,
        default_matches=default_matches,
        default_fold_matches=default_fold_matches,
        alternatives=alternatives,
        candidate_audit=tuple(
            _document(row, f"hero {hero_id} has a malformed core candidate audit")
            for row in candidate_audit
        ),
        evaluation=_document(evaluation, f"hero {hero_id} has no policy evaluation"),
    )


def _tier_policy(
    value: object,
    hero_id: int,
    items: tuple[ItemEvidence, ...],
) -> TierPolicyEvidence:
    if not isinstance(value, dict) or value.get("version") != TIER_POLICY_VERSION:
        raise ArtifactError(f"hero {hero_id} has no supported tier policy")
    raw_membership_value = value.get("item_ids_by_tier")
    if not isinstance(raw_membership_value, dict) or set(raw_membership_value) != {
        "1",
        "2",
        "3",
        "4",
    }:
        raise ArtifactError(f"hero {hero_id} has an incomplete tier policy")
    raw_membership = cast("dict[str, Any]", raw_membership_value)
    by_id = {item.item_id: item for item in items}
    item_ids_by_tier: dict[int, tuple[int, ...]] = {}
    all_item_ids: list[int] = []
    for tier in range(1, 5):
        raw_item_ids = raw_membership[str(tier)]
        if not isinstance(raw_item_ids, list):
            raise ArtifactError(f"hero {hero_id} has a malformed Tier {tier} policy")
        item_ids = tuple(
            _required_int(item_id, "tier policy item id", minimum=1)
            for item_id in raw_item_ids
        )
        if not 1 <= len(item_ids) <= TIER_ITEM_COUNT or len(item_ids) != len(
            set(item_ids)
        ):
            raise ArtifactError(f"hero {hero_id} has invalid Tier {tier} membership")
        for item_id in item_ids:
            item = by_id.get(item_id)
            if (
                item is None
                or item.tier != tier
                or item.training_adopter_matches < MINIMUM_TIER_SUPPORT
                or item.validation_adopter_matches < MINIMUM_TIER_SUPPORT
                or item.training_adoption < MINIMUM_TIER_ADOPTION
                or item.validation_adoption < MINIMUM_TIER_ADOPTION
                or abs(item.training_adoption - item.validation_adoption)
                > MAXIMUM_TIER_ADOPTION_DRIFT
            ):
                raise ArtifactError(
                    f"hero {hero_id} has an unsupported Tier {tier} item"
                )
        item_ids_by_tier[tier] = item_ids
        all_item_ids.extend(item_ids)
    if len(all_item_ids) != len(set(all_item_ids)):
        raise ArtifactError(f"hero {hero_id} repeats an item across tier menus")
    return TierPolicyEvidence(item_ids_by_tier)


def _validate_item_tier_coverage(items: tuple[ItemEvidence, ...], hero_id: int) -> None:
    for tier in range(1, 5):
        if not any(item.tier == tier for item in items):
            raise ArtifactError(f"hero {hero_id} has no Tier {tier} item evidence")


def _validate_policy_item_references(
    core_policy: CorePolicyEvidence,
    tier_policy: TierPolicyEvidence,
    sequence_policy: SequencePolicy,
    situational_policy: SituationalPolicy,
    *,
    items: tuple[ItemEvidence, ...],
    hero_id: int,
) -> None:
    item_ids = {item.item_id for item in items}
    referenced_items = (
        set(core_policy.backbone_item_ids)
        | set(core_policy.default_item_ids)
        | {row.item_id for row in core_policy.alternatives}
        | {row.comparator_item_id for row in core_policy.alternatives}
        | {
            item_id
            for tier_item_ids in tier_policy.item_ids_by_tier.values()
            for item_id in tier_item_ids
        }
        | set(sequence_policy.default_path)
        | {row.next_item_id for row in sequence_policy.transitions}
        | {branch.item_id for branch in situational_policy.branches}
        | {branch.comparator_item_id for branch in situational_policy.branches}
    )
    if not referenced_items <= item_ids:
        raise ArtifactError(f"hero {hero_id} policy references missing item evidence")
    items_by_id = {item.item_id: item for item in items}
    if any(
        items_by_id[branch.item_id].adopter_matches < MINIMUM_TIER_SUPPORT
        for branch in situational_policy.branches
    ):
        raise ArtifactError(f"hero {hero_id} has a weak situational tier item")
    core_target_ids = set(core_policy.default_item_ids)
    if any(
        branch.comparator_item_id not in core_target_ids
        or items_by_id[branch.item_id].tier != branch.tier
        or items_by_id[branch.comparator_item_id].tier != branch.tier
        for branch in situational_policy.branches
    ):
        raise ArtifactError(f"hero {hero_id} has an invalid situational comparator")


def _build_path(
    value: object,
    *,
    hero_id: int,
    hero_name: str,
) -> HeroBuildEvidence:
    if not isinstance(value, dict):
        raise ArtifactError(f"hero {hero_id} contains a malformed build path")
    path_id = value.get("path_id")
    path_label = value.get("path_label")
    raw_signature = value.get("signature_item_ids")
    discovery = value.get("discovery")
    if (
        not isinstance(path_id, str)
        or not path_id.strip()
        or not isinstance(path_label, str)
        or not path_label.strip()
        or not isinstance(raw_signature, list)
        or any(
            not isinstance(item_id, int) or item_id <= 0 for item_id in raw_signature
        )
        or len(raw_signature) != len(set(raw_signature))
        or not isinstance(discovery, dict)
    ):
        raise ArtifactError(f"hero {hero_id} has an invalid build path identity")
    eligible = _required_int(
        value.get("eligible_player_matches"), "eligible player matches", minimum=1
    )
    raw_fold_eligible = value.get("fold_eligible_player_matches")
    if not isinstance(raw_fold_eligible, dict):
        raise ArtifactError(f"hero {hero_id} lacks fold cohort counts")
    fold_eligible = {
        fold: _required_int(
            raw_fold_eligible.get(fold),
            f"{fold} eligible player matches",
            minimum=0 if fold == "test" else 1,
        )
        for fold in ("train", "validation", "test")
    }
    selection_eligible = _required_int(
        value.get("selection_eligible_player_matches"),
        "selection eligible player matches",
        minimum=1,
    )
    if (
        sum(fold_eligible.values()) != eligible
        or fold_eligible["train"] + fold_eligible["validation"] != selection_eligible
    ):
        raise ArtifactError(f"hero {hero_id} has inconsistent fold cohort counts")
    raw_items = value.get("items")
    if not isinstance(raw_items, list):
        raise ArtifactError(f"hero {hero_id} has incomplete build evidence")
    items, item_ids = _hero_items(raw_items, hero_id, eligible)
    if any(
        item.selection_eligible_player_matches != selection_eligible
        or item.training_eligible_player_matches != fold_eligible["train"]
        or item.validation_eligible_player_matches != fold_eligible["validation"]
        or item.test_eligible_player_matches != fold_eligible["test"]
        for item in items
    ):
        raise ArtifactError(f"hero {hero_id} item fold denominators disagree")
    core_policy = _core_policy(
        value.get("core_policy"), hero_id, set(item_ids), eligible
    )
    sequence_policy = _sequence_policy(value.get("sequence_policy"), hero_id)
    situational_policy = _situational_policy(value.get("situational_policy"), hero_id)
    tier_policy = _tier_policy(value.get("tier_policy"), hero_id, items)
    _validate_policy_item_references(
        core_policy,
        tier_policy,
        sequence_policy,
        situational_policy,
        items=items,
        hero_id=hero_id,
    )
    return HeroBuildEvidence(
        hero_id=hero_id,
        hero=hero_name,
        eligible_player_matches=eligible,
        selection_eligible_player_matches=selection_eligible,
        fold_eligible_player_matches=fold_eligible,
        median_final_net_worth=_required_int(
            value.get("median_final_net_worth"), "median final net worth", minimum=1
        ),
        items=items,
        core_policy=core_policy,
        tier_policy=tier_policy,
        sequence_policy=sequence_policy,
        situational_policy=situational_policy,
        path_id=path_id.strip(),
        path_label=path_label.strip(),
        signature_item_ids=tuple(
            _required_int(item_id, "signature item id", minimum=1)
            for item_id in raw_signature
        ),
        discovery=_document(
            discovery,
            f"hero {hero_id} path {path_id} has malformed discovery evidence",
        ),
    )


def _hero_builds(value: object) -> tuple[int, tuple[HeroBuildEvidence, ...]]:
    if not isinstance(value, dict):
        raise ArtifactError("build evidence contains a malformed hero")
    hero_id = _required_int(value.get("hero_id"), "hero id", minimum=1)
    name = value.get("hero")
    raw_builds = value.get("builds")
    if not isinstance(name, str) or not name.strip():
        raise ArtifactError(f"hero {hero_id} has no name")
    if not isinstance(raw_builds, list) or not raw_builds:
        raise ArtifactError(f"hero {hero_id} has no supported build paths")
    builds = tuple(
        _build_path(build, hero_id=hero_id, hero_name=name.strip())
        for build in raw_builds
    )
    path_ids = [build.path_id for build in builds]
    if len(path_ids) != len(set(path_ids)):
        raise ArtifactError(f"hero {hero_id} contains duplicate build paths")
    return hero_id, builds


def _epoch(value: object, label: str) -> EpochBoundary:
    if not isinstance(value, dict):
        raise ArtifactError(f"build evidence lacks the {label} epoch")
    identity = value.get("identity")
    if not isinstance(identity, str):
        raise ArtifactError(f"build evidence has an invalid {label} epoch")
    return EpochBoundary(
        identity,
        _required_int(value.get("start_timestamp"), f"{label} epoch timestamp"),
    )


def load_build_evidence(path: Path) -> BuildEvidenceCatalog:
    try:
        raw = path.read_bytes()
        document = json.loads(raw)
    except (OSError, json.JSONDecodeError) as error:
        raise ArtifactError(f"could not read build evidence {path}: {error}") from error
    if not isinstance(document, dict):
        raise ArtifactError("build evidence root must be an object")
    artifact_id = document.get("artifact_id")
    payload = {key: value for key, value in document.items() if key != "artifact_id"}
    if not isinstance(artifact_id, str) or artifact_id != sha256_json(payload):
        raise ArtifactError("build evidence fingerprint does not match its contents")
    if document.get("schema_version") != BUILD_EVIDENCE_SCHEMA_VERSION:
        raise ArtifactError("unsupported build-evidence schema")
    method = document.get("method")
    expected_method = {
        "version": METHOD_VERSION,
        "minimum_core_item_count": MINIMUM_BACKBONE_ITEM_COUNT,
        "maximum_core_item_count": MAXIMUM_CORE_ITEM_COUNT,
        "minimum_core_support": MINIMUM_CORE_SUPPORT,
        "minimum_tier_support": MINIMUM_TIER_SUPPORT,
        "minimum_tier_adoption": MINIMUM_TIER_ADOPTION,
        "maximum_tier_adoption_drift": MAXIMUM_TIER_ADOPTION_DRIFT,
        "tier_item_count": TIER_ITEM_COUNT,
        "minimum_purchase_window_coverage": MINIMUM_PURCHASE_WINDOW_COVERAGE,
        "minimum_purchase_window_observations": MINIMUM_PURCHASE_WINDOW_OBSERVATIONS,
        "minimum_imbue_support": MINIMUM_IMBUE_SUPPORT,
        "minimum_imbue_share": MINIMUM_IMBUE_SHARE,
    }
    if not isinstance(method, dict) or any(
        method.get(key) != value for key, value in expected_method.items()
    ):
        raise ArtifactError("build evidence uses an unsupported selection method")
    raw_heroes = document.get("heroes")
    requested = document.get("requested_hero_ids")
    patch = document.get("patch")
    cohort = document.get("cohort")
    epochs = document.get("epochs")
    if (
        not isinstance(raw_heroes, list)
        or not isinstance(requested, list)
        or not isinstance(patch, dict)
        or not isinstance(patch.get("identity"), str)
        or not isinstance(cohort, dict)
        or not isinstance(epochs, dict)
    ):
        raise ArtifactError("build evidence has an incomplete identity header")
    hero_rows = tuple(_hero_builds(row) for row in raw_heroes)
    hero_builds = dict(hero_rows)
    if len(hero_builds) != len(hero_rows):
        raise ArtifactError("build evidence contains duplicate heroes")
    by_id = {
        hero_id: max(
            builds,
            key=lambda build: (build.eligible_player_matches, build.path_id),
        )
        for hero_id, builds in hero_builds.items()
    }
    requested_ids = frozenset(
        _required_int(hero_id, "requested hero id", minimum=1) for hero_id in requested
    )
    if len(requested_ids) != len(requested):
        raise ArtifactError("build evidence contains duplicate requested heroes")
    if requested_ids != set(by_id):
        raise ArtifactError("build evidence does not exactly cover requested heroes")
    catalog = BuildEvidenceCatalog(
        artifact_id=artifact_id,
        client_version=_required_int(
            document.get("client_version"), "client version", minimum=1
        ),
        patch=patch,
        cohort=cohort,
        epochs=EpochSet(
            mechanics=_epoch(epochs.get("mechanics"), "mechanics"),
            matchmaking=_epoch(epochs.get("matchmaking"), "matchmaking"),
            map_objectives=_epoch(epochs.get("map_objectives"), "map objectives"),
            telemetry=_epoch(epochs.get("telemetry"), "telemetry"),
        ),
        rank_labels_sha256=_required_sha256(
            document.get("rank_labels_sha256"), "rank-label fingerprint"
        ),
        heroes_sha256=_required_sha256(
            document.get("heroes_sha256"), "hero fingerprint"
        ),
        items_sha256=_required_sha256(document.get("items_sha256"), "item fingerprint"),
        requested_hero_ids=requested_ids,
        heroes=by_id,
        hero_builds=hero_builds,
        raw_bytes=raw,
    )
    _required_sha256(catalog.patch.get("identity"), "patch fingerprint")
    _ = catalog.as_of_timestamp
    if catalog.as_of_timestamp < catalog.epochs.analysis_start_timestamp:
        raise ArtifactError("build evidence as-of cutoff precedes an epoch boundary")
    return catalog


def assert_build_evidence_compatible(
    catalog: BuildEvidenceCatalog,
    *,
    patch_identity: str,
    client_version: int,
    as_of_timestamp: int,
    match_mode: MatchMode,
    rank_range: RankRange,
    rank_catalog: RankCatalog,
    heroes: list[dict[str, Any]],
    assets: list[dict[str, Any]],
    epochs: EpochSet,
) -> None:
    cohort_mode = str(catalog.cohort.get("match_mode") or "").casefold()
    cohort_game = str(catalog.cohort.get("game_mode") or "").casefold()
    differences = []
    checks = {
        "patch": catalog.patch.get("identity") == patch_identity,
        "client_version": catalog.client_version == client_version,
        "as_of_timestamp": catalog.as_of_timestamp == as_of_timestamp,
        "match_mode": cohort_mode == match_mode.value,
        "game_mode": cohort_game == "normal",
        "minimum_badge": catalog.cohort.get("minimum_badge")
        == rank_range.minimum.badge_id,
        "maximum_badge": catalog.cohort.get("maximum_badge")
        == rank_range.maximum.badge_id,
        "rank_labels": catalog.rank_labels_sha256 == rank_catalog.sha256,
        "heroes": catalog.heroes_sha256 == sha256_json(heroes),
        "items": catalog.items_sha256 == sha256_json(assets),
        "epochs": catalog.epochs == epochs,
    }
    differences.extend(key for key, compatible in checks.items() if not compatible)
    if differences:
        raise ArtifactError(
            "build evidence is incompatible in: " + ", ".join(sorted(differences))
        )


def _replay_component_path(
    graph: ItemGraph,
    evidence_by_id: dict[int, ItemEvidence],
    path: tuple[int, ...],
) -> InventoryState:
    state = InventoryState()
    for item_id in path:
        if item_id not in evidence_by_id:
            raise MechanicsError(f"purchase path item {item_id} lacks evidence")
        missing = [
            component_id
            for component_id in graph.components[item_id]
            if component_id not in state.owned
        ]
        if missing:
            raise MechanicsError(
                f"purchase path item {item_id} precedes components {missing}"
            )
        state = purchase_item(graph, state, item_id)
    return state


def _expand_component_path(
    graph: ItemGraph,
    targets: tuple[int, ...],
    evidence_by_id: dict[int, ItemEvidence],
) -> tuple[int, ...]:
    priorities = {
        item_id: (
            item.selection_median_valid_buy_net_worth
            if item.selection_median_valid_buy_net_worth is not None
            else math.inf,
            item.selection_median_buy_time_s
            if item.selection_median_buy_time_s is not None
            else math.inf,
            item_id,
        )
        for item_id, item in evidence_by_id.items()
    }
    return schedule_component_path(graph, targets, priorities)


def _select_core_candidate(
    graph: ItemGraph,
    evidence: HeroBuildEvidence,
    by_id: dict[int, ItemEvidence],
) -> tuple[CoreCandidate, tuple[int, ...], int]:
    selected_order = evidence.core_policy.default_item_ids
    candidate = CoreCandidate(
        item_ids=tuple(sorted(selected_order)),
        joint_matches=evidence.core_policy.default_matches,
    )
    cost = sum(graph.require(item_id).cost for item_id in candidate.item_ids)
    if cost > evidence.median_final_net_worth:
        raise ArtifactError(
            f"hero {evidence.hero_id} default core exceeds cohort wealth"
        )
    try:
        candidate_path = _expand_component_path(graph, selected_order, by_id)
        state = _replay_component_path(graph, by_id, candidate_path)
    except MechanicsError as error:
        raise ArtifactError(
            f"hero {evidence.hero_id} has an illegal state-aware core: {error}"
        ) from error
    if len(candidate_path) != len(set(candidate_path)) or set(state.owned) != set(
        candidate.item_ids
    ):
        raise ArtifactError(f"hero {evidence.hero_id} has no legal state-aware core")
    return candidate, selected_order, cost


def _validate_item_assets(
    evidence: HeroBuildEvidence,
    assets_by_id: dict[int, dict[str, Any]],
) -> None:
    for item in evidence.items:
        asset = assets_by_id.get(item.item_id)
        if (
            asset is None
            or str(asset.get("name") or "") != item.item
            or int(asset.get("item_tier") or 0) != item.tier
            or int(asset.get("cost") or 0) != item.cost
            or str(asset.get("item_slot_type") or "unknown").casefold() != item.slot
            or bool(asset.get("is_active_item")) != item.active
        ):
            raise ArtifactError(
                f"hero {evidence.hero_id} item {item.item_id} conflicts with assets"
            )


def _replay_selected_path(
    graph: ItemGraph,
    evidence: HeroBuildEvidence,
    by_id: dict[int, ItemEvidence],
    selected: CoreCandidate,
    selected_order: tuple[int, ...],
) -> tuple[int, ...]:
    window_bounds: dict[int, tuple[float, float]] = {}
    for item in by_id.values():
        window = reliable_purchase_window(item)
        if window is not None:
            window_bounds[item.item_id] = window
    path_ids = (
        evidence.sequence_policy.default_path
        if evidence.sequence_policy is not None
        else _expand_component_path(graph, selected_order, by_id)
    )
    if len(path_ids) != len(set(path_ids)):
        raise ArtifactError(
            f"hero {evidence.hero_id} component-expanded path repeats an item"
        )
    if nondecreasing_window_schedule(path_ids, window_bounds) is None:
        raise ArtifactError(
            f"hero {evidence.hero_id} component-expanded path violates "
            "first-ownership soul windows"
        )
    try:
        state = _replay_component_path(graph, by_id, path_ids)
    except MechanicsError as error:
        raise ArtifactError(
            f"hero {evidence.hero_id} has an invalid component-expanded path: {error}"
        ) from error
    if set(state.owned) == set(selected.item_ids):
        return path_ids
    fallback = _expand_component_path(graph, selected_order, by_id)
    if len(fallback) != len(set(fallback)):
        raise ArtifactError(
            f"hero {evidence.hero_id} component-expanded path repeats an item"
        )
    if nondecreasing_window_schedule(fallback, window_bounds) is None:
        raise ArtifactError(
            f"hero {evidence.hero_id} fallback path violates first-ownership "
            "soul windows"
        )
    state = _replay_component_path(graph, by_id, fallback)
    if set(state.owned) != set(selected.item_ids):
        raise ArtifactError(
            f"hero {evidence.hero_id} component-expanded path does not end in CORE"
        )
    return fallback


def _tier_selection(
    evidence: HeroBuildEvidence,
    tier: int,
    core_ids: set[int],
    optional_core_ids: set[int],
    *,
    graph: ItemGraph,
    visible_higher_tier_ids: set[int],
) -> tuple[ItemEvidence, ...]:
    def has_visible_upgrade(item: ItemEvidence) -> bool:
        upgrades = set(graph.children[item.item_id])
        return not upgrades or bool(upgrades & visible_higher_tier_ids)

    by_id = {item.item_id: item for item in evidence.items}
    membership = tuple(
        by_id[item_id] for item_id in evidence.tier_policy.item_ids_by_tier[tier]
    )
    if any(
        item.item_id in core_ids
        or item.item_id in optional_core_ids
        or not has_visible_upgrade(item)
        for item in membership
    ):
        raise ArtifactError(
            f"hero {evidence.hero_id} has an invalid Tier {tier} policy"
        )
    expected_order = tuple(
        sorted(
            membership,
            key=lambda item: (
                reliable_purchase_window(item) is None,
                (
                    item.selection_median_valid_buy_net_worth
                    if reliable_purchase_window(item) is not None
                    and item.selection_median_valid_buy_net_worth is not None
                    else math.inf
                ),
                (
                    item.selection_median_buy_time_s
                    if reliable_purchase_window(item) is not None
                    and item.selection_median_buy_time_s is not None
                    else math.inf
                ),
                item.item_id,
            ),
        )
    )
    if membership != expected_order:
        raise ArtifactError(
            f"hero {evidence.hero_id} Tier {tier} policy order is not deterministic"
        )
    return membership


def select_hero_build(
    evidence: HeroBuildEvidence,
    assets: list[dict[str, Any]],
) -> SelectedHeroBuild:
    graph = ItemGraph.from_assets(assets)
    assets_by_id = {
        int(asset["id"]): asset for asset in assets if isinstance(asset.get("id"), int)
    }
    by_id = {item.item_id: item for item in evidence.items}
    _validate_item_assets(evidence, assets_by_id)

    selected, selected_order, selected_cost = _select_core_candidate(
        graph, evidence, by_id
    )

    for branch in (
        evidence.situational_policy.branches if evidence.situational_policy else ()
    ):
        replacement = tuple(
            branch.item_id if item_id == branch.comparator_item_id else item_id
            for item_id in selected_order
        )
        try:
            replacement_path = _expand_component_path(graph, replacement, by_id)
            replacement_state = _replay_component_path(
                graph,
                by_id,
                replacement_path,
            )
        except MechanicsError as error:
            raise ArtifactError(
                f"hero {evidence.hero_id} has an illegal situational replacement"
            ) from error
        if len(replacement) != len(set(replacement)) or set(
            replacement_state.owned
        ) != set(replacement):
            raise ArtifactError(
                f"hero {evidence.hero_id} has an illegal situational replacement"
            )

    path_ids = _replay_selected_path(graph, evidence, by_id, selected, selected_order)

    tiers: dict[int, tuple[ItemEvidence, ...]] = {}
    core_ids = set(path_ids)
    optional_core_ids = {
        alternative.item_id for alternative in evidence.core_policy.alternatives
    }
    situational_ids = {
        branch.item_id
        for branch in (
            evidence.situational_policy.branches if evidence.situational_policy else ()
        )
    }
    if situational_ids & core_ids:
        raise ArtifactError(
            f"hero {evidence.hero_id} situational items repeat the selected CORE"
        )
    visible_higher_tier_ids = core_ids | optional_core_ids
    for tier in range(4, 0, -1):
        tiers[tier] = _tier_selection(
            evidence,
            tier,
            core_ids,
            optional_core_ids,
            graph=graph,
            visible_higher_tier_ids=visible_higher_tier_ids,
        )
        visible_higher_tier_ids.update(item.item_id for item in tiers[tier])
    if not situational_ids <= {
        item.item_id for tier_items in tiers.values() for item in tier_items
    }:
        raise ArtifactError(
            f"hero {evidence.hero_id} situational items are absent from tier policy"
        )
    return SelectedHeroBuild(
        hero_id=evidence.hero_id,
        path_id=evidence.path_id,
        path_label=evidence.path_label,
        signature_item_ids=evidence.signature_item_ids,
        core=tuple(by_id[item_id] for item_id in selected_order),
        core_purchase_path=tuple(by_id[item_id] for item_id in path_ids),
        tiers=tiers,
        backbone=tuple(
            by_id[item_id] for item_id in evidence.core_policy.backbone_item_ids
        ),
        optional_core=tuple(
            by_id[alternative.item_id]
            for alternative in sorted(
                evidence.core_policy.alternatives,
                key=lambda row: (row.stage, row.item_id),
            )
        ),
        core_alternatives=evidence.core_policy.alternatives,
        backbone_matches=evidence.core_policy.backbone_matches,
        backbone_share=(
            evidence.core_policy.backbone_matches
            / evidence.selection_eligible_player_matches
        ),
        core_joint_matches=selected.joint_matches,
        core_joint_share=(
            selected.joint_matches / evidence.selection_eligible_player_matches
        ),
        median_final_net_worth=evidence.median_final_net_worth,
        core_target_cost=selected_cost,
    )


def evidence_record_sha256(catalog: BuildEvidenceCatalog) -> str:
    return hashlib.sha256(catalog.raw_bytes).hexdigest()
