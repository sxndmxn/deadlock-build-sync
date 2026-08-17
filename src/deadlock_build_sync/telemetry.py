from __future__ import annotations

import math
import operator
from collections import Counter, defaultdict
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .mechanics import ItemGraph, MechanicsError
from .purchase_guide import wilson_score_interval
from .snapshot import EvidenceUnit, MatchMode, OutcomePolicy

EARLY_NET_WORTH_CUTOFF_S = 180
MAX_PRECEDING_NET_WORTH_AGE_S = 60


class TelemetryError(ValueError):
    """Raised when telemetry cannot support the declared estimand."""


@dataclass(frozen=True)
class OutcomeRow:
    won: bool
    scored: bool = True
    penalized: bool = False
    party_penalized: bool = False
    abandoned: bool = False
    rewarded: bool = True
    low_priority: bool = False
    new_player: bool = False


def outcome_is_eligible(row: OutcomeRow, policy: OutcomePolicy) -> bool:
    """Apply exclusions before considering the outcome value.

    Returns:
        Whether this player appearance belongs in outcome-dependent evidence.

    """
    return not (
        (policy.exclude_not_scored and not row.scored)
        or (policy.exclude_penalized and row.penalized)
        or (policy.exclude_party_penalized and row.party_penalized)
        or (policy.exclude_abandoned and row.abandoned)
        or (policy.exclude_unrewarded and not row.rewarded)
        or (policy.exclude_low_priority and row.low_priority)
        or (policy.exclude_new_player and row.new_player)
    )


@dataclass(frozen=True)
class PurchaseEvent:
    match_id: int
    player_slot: int
    account_id: int | None
    item_id: int
    time_s: int
    net_worth: int | None = None
    preceding_net_worth: int | None = None
    preceding_time_s: int | None = None
    final_net_worth: int | None = None

    @property
    def appearance_id(self) -> tuple[int, int]:
        return self.match_id, self.player_slot


@dataclass(frozen=True)
class AdoptionEstimate:
    item_id: int
    eligible_appearances: int
    first_ownerships: int
    purchase_events: int
    unique_accounts: int
    adoption: float
    interval: tuple[float, float]
    unit: EvidenceUnit = EvidenceUnit.ELIGIBLE_APPEARANCE


def estimate_item_adoption(
    item_id: int,
    eligible_appearances: set[tuple[int, int]],
    events: tuple[PurchaseEvent, ...],
) -> AdoptionEstimate:
    """Estimate unique first ownership per eligible player-match appearance.

    Returns:
        Adoption, event-volume, and unique-account denominators kept separately.

    """
    eligible_events = tuple(
        event
        for event in events
        if event.item_id == item_id and event.appearance_id in eligible_appearances
    )
    owners = {event.appearance_id for event in eligible_events}
    accounts = {
        event.account_id for event in eligible_events if event.account_id is not None
    }
    denominator = len(eligible_appearances)
    lower, upper = wilson_score_interval(len(owners), denominator)
    return AdoptionEstimate(
        item_id=item_id,
        eligible_appearances=denominator,
        first_ownerships=len(owners),
        purchase_events=len(eligible_events),
        unique_accounts=len(accounts),
        adoption=len(owners) / denominator if denominator else 0.0,
        interval=(lower, upper),
    )


def validated_purchase_net_worth(event: PurchaseEvent) -> int | None:
    """Admit only temporally valid purchase-time net worth.

    Returns:
        Trusted pre-decision net worth or ``None`` for unsupported opening values.

    Raises:
        TelemetryError: If telemetry exhibits the documented final-snapshot fallback.

    """
    if event.time_s >= EARLY_NET_WORTH_CUTOFF_S:
        return event.net_worth
    if (
        event.net_worth is not None
        and event.final_net_worth is not None
        and event.net_worth == event.final_net_worth
    ):
        raise TelemetryError(
            "pre-180-second purchase net worth equals the final-snapshot fallback"
        )
    if (
        event.preceding_net_worth is not None
        and event.preceding_time_s is not None
        and 0 <= event.preceding_time_s <= event.time_s
        and event.time_s - event.preceding_time_s <= MAX_PRECEDING_NET_WORTH_AGE_S
    ):
        return event.preceding_net_worth
    return None


class CompetingEvent(StrEnum):
    PURCHASE = "first_purchase"
    SUBSTITUTE = "substitute_purchase"
    INELIGIBLE = "ineligible"
    GAME_END = "game_end"


@dataclass(frozen=True)
class FirstPurchaseObservation:
    appearance_id: tuple[int, int]
    time_s: int
    event: CompetingEvent


@dataclass(frozen=True)
class HazardPoint:
    time_s: int
    at_risk: int
    purchases: int
    competing_events: int
    cause_specific_hazard: float
    cumulative_incidence: float


def first_purchase_cumulative_incidence(
    observations: tuple[FirstPurchaseObservation, ...],
) -> tuple[HazardPoint, ...]:
    """Estimate first-purchase incidence with explicit competing events.

    Returns:
        Discrete cause-specific hazards and cumulative incidence by event time.

    Raises:
        TelemetryError: If an appearance contributes more than one terminal event.

    """
    appearance_ids = [observation.appearance_id for observation in observations]
    if len(set(appearance_ids)) != len(appearance_ids):
        raise TelemetryError("each appearance must have one first terminal event")
    at_risk = len(observations)
    survival = 1.0
    cumulative_incidence = 0.0
    result: list[HazardPoint] = []
    by_time: dict[int, list[FirstPurchaseObservation]] = defaultdict(list)
    for observation in observations:
        if observation.time_s < 0:
            raise TelemetryError("event time must be non-negative")
        by_time[observation.time_s].append(observation)
    for event_time, current in sorted(by_time.items()):
        purchases = sum(
            observation.event == CompetingEvent.PURCHASE for observation in current
        )
        competing = len(current) - purchases
        hazard = purchases / at_risk if at_risk else 0.0
        cumulative_incidence += survival * hazard
        all_event_hazard = len(current) / at_risk if at_risk else 0.0
        result.append(
            HazardPoint(
                time_s=event_time,
                at_risk=at_risk,
                purchases=purchases,
                competing_events=competing,
                cause_specific_hazard=hazard,
                cumulative_incidence=cumulative_incidence,
            )
        )
        survival *= 1 - all_event_hazard
        at_risk -= len(current)
    return tuple(result)


class InventoryEventKind(StrEnum):
    PURCHASE = "purchase"
    SELL = "sell"


@dataclass(frozen=True)
class InventoryEvent:
    time_s: int
    sequence: int
    kind: InventoryEventKind
    item_id: int
    upgrade_flag: bool = False


@dataclass(frozen=True)
class ReconstructedEvent:
    event: InventoryEvent
    classification: str
    owned_after: tuple[int, ...]
    cash_required: int = 0


def _apply_purchase_event(
    graph: ItemGraph,
    event: InventoryEvent,
    owned: list[int],
    consumed_at: Counter[tuple[int, int]],
) -> tuple[str, int]:
    cash_required = graph.incremental_cash_cost(event.item_id, tuple(owned))
    consumed = [
        component for component in graph.components[event.item_id] if component in owned
    ]
    for component in consumed:
        owned.remove(component)
        consumed_at[event.time_s, component] += 1
    owned.append(event.item_id)
    classification = (
        "upgrade_purchase" if consumed or event.upgrade_flag else "purchase"
    )
    return classification, cash_required


def _apply_sale_event(
    event: InventoryEvent,
    owned: list[int],
    consumed_at: Counter[tuple[int, int]],
) -> str:
    consumed_key = event.time_s, event.item_id
    if event.item_id in owned:
        owned.remove(event.item_id)
        return "discretionary_sell"
    if consumed_at[consumed_key]:
        consumed_at[consumed_key] -= 1
        return "upgrade_consumption"
    raise TelemetryError(f"cannot reconstruct sell of unowned item {event.item_id}")


def reconstruct_inventory_events(
    graph: ItemGraph,
    events: tuple[InventoryEvent, ...],
) -> tuple[ReconstructedEvent, ...]:
    """Reconstruct ownership while separating upgrade consumption from sells.

    Returns:
        Ordered event classifications and post-event inventories.

    Raises:
        TelemetryError: If an explicit sell targets an unowned item.

    """
    ordered = sorted(
        events,
        key=lambda event: (
            event.time_s,
            0 if event.kind == InventoryEventKind.PURCHASE else 1,
            event.sequence,
        ),
    )
    owned: list[int] = []
    consumed_at: Counter[tuple[int, int]] = Counter()
    result: list[ReconstructedEvent] = []
    for event in ordered:
        try:
            graph.require(event.item_id)
        except MechanicsError as error:
            raise TelemetryError(str(error)) from error
        if event.kind == InventoryEventKind.PURCHASE:
            classification, cash_required = _apply_purchase_event(
                graph,
                event,
                owned,
                consumed_at,
            )
        else:
            classification = _apply_sale_event(event, owned, consumed_at)
            cash_required = 0
        result.append(
            ReconstructedEvent(
                event=event,
                classification=classification,
                owned_after=tuple(owned),
                cash_required=cash_required,
            )
        )
    return tuple(result)


@dataclass(frozen=True)
class RateEstimate:
    wins: int
    observations: int
    estimate: float
    interval: tuple[float, float]
    baseline: float
    unit: EvidenceUnit
    label: str = "observational descriptive rate"


def descriptive_rate(
    *,
    wins: int,
    observations: int,
    baseline: float,
    unit: EvidenceUnit,
) -> RateEstimate:
    """Construct a support-bearing observational proportion.

    Returns:
        Rate, Wilson interval, baseline, and declared analytic unit.

    Raises:
        TelemetryError: If counts or the baseline are invalid.

    """
    if wins < 0 or observations < wins or not 0 <= baseline <= 1:
        raise TelemetryError("invalid descriptive-rate inputs")
    interval = wilson_score_interval(wins, observations)
    return RateEstimate(
        wins=wins,
        observations=observations,
        estimate=wins / observations if observations else 0.0,
        interval=interval,
        baseline=baseline,
        unit=unit,
    )


def empirical_bayes_rate(
    wins: int,
    observations: int,
    *,
    baseline: float,
    prior_strength: float,
) -> float:
    """Shrink a binomial cell toward a declared empirical baseline.

    Returns:
        Posterior mean under a beta prior.

    Raises:
        TelemetryError: If counts, baseline, or prior strength are invalid.

    """
    if observations < wins or wins < 0 or prior_strength < 0 or not 0 <= baseline <= 1:
        raise TelemetryError("invalid shrinkage inputs")
    denominator = observations + prior_strength
    if denominator == 0:
        return baseline
    return (wins + baseline * prior_strength) / denominator


@dataclass(frozen=True)
class CandidateEffect:
    key: str
    wins: int
    observations: int

    @property
    def estimate(self) -> float:
        return self.wins / self.observations if self.observations else 0.0


def select_then_estimate(
    selection: tuple[CandidateEffect, ...],
    estimation: tuple[CandidateEffect, ...],
    *,
    minimum_support: int,
) -> CandidateEffect | None:
    """Select on one fold and report only the disjoint estimation fold.

    Returns:
        The held-out estimate for the selected key, or ``None`` when unsupported.

    """
    eligible = [row for row in selection if row.observations >= minimum_support]
    if not eligible:
        return None
    selected = min(
        eligible,
        key=lambda row: (-row.estimate, -row.observations, row.key),
    )
    estimates = {row.key: row for row in estimation}
    held_out = estimates.get(selected.key)
    if held_out is None or held_out.observations < minimum_support:
        return None
    return held_out


@dataclass(frozen=True)
class AbilityDecision:
    position: int
    prefix: tuple[int, ...]
    reached: int
    next_counts: dict[int, int]
    next_probabilities: dict[int, float]


@dataclass(frozen=True)
class AbilityDecisionReport:
    all_appearances: int
    valid_telemetry_appearances: int
    complete_path_appearances: int
    retained_path_appearances: int
    decisions: tuple[AbilityDecision, ...]


def _validated_ability_path(
    abilities: object,
    valid_ability_ids: set[int],
) -> tuple[int, ...] | None:
    if not isinstance(abilities, list) or not abilities or len(abilities) > 16:
        return None
    validated: list[int] = []
    for ability_id in abilities:
        if not isinstance(ability_id, int):
            return None
        validated.append(ability_id)
    path = tuple(validated)
    if not set(path) <= valid_ability_ids:
        return None
    if any(count > 4 for count in Counter(path).values()):
        return None
    return path


def aggregate_ability_prefixes(
    rows: list[dict[str, Any]],
    *,
    valid_ability_ids: set[int],
    all_appearances: int,
    minimum_path_support: int = 1,
) -> AbilityDecisionReport:
    """Aggregate variable-length paths into decision-reached prefix probabilities.

    Returns:
        Separate denominators and every retained prefix decision.

    """
    paths: list[tuple[tuple[int, ...], int]] = []
    valid_telemetry = 0
    complete = 0
    for row in rows:
        abilities = row.get("abilities")
        matches = int(row.get("matches") or 0)
        path = _validated_ability_path(abilities, valid_ability_ids)
        if path is None or matches <= 0:
            continue
        valid_telemetry += matches
        if len(path) == 16:
            complete += matches
        if matches >= minimum_path_support:
            paths.append((path, matches))
    retained = sum(matches for _, matches in paths)
    counts: dict[tuple[int, ...], Counter[int]] = defaultdict(Counter)
    for path, matches in paths:
        for index, ability_id in enumerate(path):
            counts[path[:index]][ability_id] += matches
    decisions = []
    for prefix, next_counts in sorted(counts.items(), key=operator.itemgetter(0)):
        reached = sum(next_counts.values())
        decisions.append(
            AbilityDecision(
                position=len(prefix) + 1,
                prefix=prefix,
                reached=reached,
                next_counts=dict(sorted(next_counts.items())),
                next_probabilities={
                    ability_id: count / reached
                    for ability_id, count in sorted(next_counts.items())
                },
            )
        )
    return AbilityDecisionReport(
        all_appearances=all_appearances,
        valid_telemetry_appearances=valid_telemetry,
        complete_path_appearances=complete,
        retained_path_appearances=retained,
        decisions=tuple(decisions),
    )


class MatchupScope(StrEnum):
    SAME_LANE = "same_lane"
    WHOLE_ENEMY_TEAM = "whole_enemy_team"


@dataclass(frozen=True)
class MatchupPair:
    match_id: int
    focal_appearance: tuple[int, int]
    enemy_hero_id: int
    won: bool
    scope: MatchupScope


@dataclass(frozen=True)
class MatchupEstimate:
    enemy_hero_id: int
    scope: MatchupScope
    pair_rows: int
    focal_appearances: int
    raw_rate: float
    shrunk_rate: float
    interval: tuple[float, float]


def estimate_matchups(
    pairs: tuple[MatchupPair, ...],
    *,
    scope: MatchupScope,
    baseline: float,
    prior_strength: float,
) -> tuple[MatchupEstimate, ...]:
    """Keep lane/team pair estimands separate and shrink sparse cells.

    Returns:
        One support-bearing estimate per enemy hero for the requested scope.

    """
    selected = [pair for pair in pairs if pair.scope == scope]
    by_enemy: dict[int, list[MatchupPair]] = defaultdict(list)
    for pair in selected:
        by_enemy[pair.enemy_hero_id].append(pair)
    result = []
    for enemy_id, rows in sorted(by_enemy.items()):
        wins = sum(row.won for row in rows)
        observations = len(rows)
        result.append(
            MatchupEstimate(
                enemy_hero_id=enemy_id,
                scope=scope,
                pair_rows=observations,
                focal_appearances=len({row.focal_appearance for row in rows}),
                raw_rate=wins / observations,
                shrunk_rate=empirical_bayes_rate(
                    wins,
                    observations,
                    baseline=baseline,
                    prior_strength=prior_strength,
                ),
                interval=wilson_score_interval(wins, observations),
            )
        )
    return tuple(result)


@dataclass(frozen=True)
class LandmarkObservation:
    match_id: int
    duration_s: int
    won: bool


@dataclass(frozen=True)
class LandmarkEstimate:
    landmark_s: int
    at_risk: int
    wins: int
    estimate: float
    interval: tuple[float, float]


def estimate_landmarks(
    observations: tuple[LandmarkObservation, ...],
    landmarks: tuple[int, ...],
) -> tuple[LandmarkEstimate, ...]:
    """Condition future-outcome estimates on games still active at each landmark.

    Returns:
        At-risk counts, rates, and intervals for each landmark.

    """
    result = []
    for landmark in sorted(set(landmarks)):
        active = [row for row in observations if row.duration_s >= landmark]
        wins = sum(row.won for row in active)
        result.append(
            LandmarkEstimate(
                landmark_s=landmark,
                at_risk=len(active),
                wins=wins,
                estimate=wins / len(active) if active else 0.0,
                interval=wilson_score_interval(wins, len(active)),
            )
        )
    return tuple(result)


_FORBIDDEN_PREDECISION_SOURCES = frozenset({
    "final_net_worth",
    "final_duration",
    "future_item",
    "eventual_buyer",
    "normalized_duration",
})


@dataclass(frozen=True)
class StateFeature:
    name: str
    value: Any
    source_event: str
    available_at: int
    stale_after_s: int

    def validate_for(self, decision_time: int) -> None:
        """Reject future, stale, and explicitly post-decision features.

        Raises:
            TelemetryError: If this value was unavailable or invalid at decision time.

        """
        if self.source_event in _FORBIDDEN_PREDECISION_SOURCES:
            raise TelemetryError(f"feature {self.name} leaks {self.source_event}")
        if self.available_at > decision_time:
            raise TelemetryError(
                f"feature {self.name} was not available at decision time"
            )
        if self.stale_after_s < 0:
            raise TelemetryError(f"feature {self.name} has invalid staleness")
        if decision_time - self.available_at > self.stale_after_s:
            raise TelemetryError(f"feature {self.name} was stale at decision time")


@dataclass(frozen=True)
class CohortWindow:
    minimum_badge: int
    maximum_badge: int
    start_timestamp: int
    end_timestamp: int
    support: int
    match_mode: MatchMode = MatchMode.RANKED
    epoch_identity: str = "current"


def _validate_cohort_window(
    window: CohortWindow,
    previous: CohortWindow | None,
) -> None:
    if window.minimum_badge > window.maximum_badge:
        raise TelemetryError("cohort rank range is inverted")
    if window.start_timestamp >= window.end_timestamp:
        raise TelemetryError("cohort time range is empty")
    if window.support < 0:
        raise TelemetryError("cohort support is negative")
    if not window.epoch_identity.strip():
        raise TelemetryError("cohort epoch identity is empty")
    if previous is not None and (
        window.minimum_badge > previous.minimum_badge
        or window.maximum_badge < previous.maximum_badge
        or window.start_timestamp > previous.start_timestamp
        or window.end_timestamp < previous.end_timestamp
    ):
        raise TelemetryError("cohort expansion must monotonically widen")


def widen_sparse_cohort(
    windows: tuple[CohortWindow, ...],
    *,
    minimum_support: int,
) -> tuple[CohortWindow, ...]:
    """Return the deterministic prefix ending at the first adequate same-regime cohort.

    Returns:
        Original then progressively wider predeclared windows, or all windows before abstention.

    """
    selected: list[CohortWindow] = []
    regime: tuple[MatchMode, str] | None = None
    for window in windows:
        window_regime = (window.match_mode, window.epoch_identity)
        if regime is None:
            regime = window_regime
        elif window_regime != regime:
            break
        _validate_cohort_window(window, selected[-1] if selected else None)
        selected.append(window)
        if window.support >= minimum_support:
            break
    return tuple(selected)


def bonferroni_alpha(alpha: float, comparisons: int) -> float:
    """Return a family-wise error controlled per-comparison alpha.

    Returns:
        Bonferroni-adjusted alpha.

    Raises:
        TelemetryError: If alpha or comparison count is invalid.

    """
    if not 0 < alpha < 1 or comparisons <= 0:
        raise TelemetryError("invalid multiplicity inputs")
    return alpha / comparisons


def effective_support(weights: tuple[float, ...]) -> float:
    """Compute Kish effective support for weighted evidence.

    Returns:
        Effective sample size, or zero for no positive weight.

    """
    total = sum(weights)
    squared = sum(weight * weight for weight in weights)
    return total * total / squared if squared else 0.0


def standard_error(proportion: float, observations: int) -> float:
    """Return the binomial standard error for diagnostics.

    Returns:
        Standard error, or infinity without observations.

    """
    if observations <= 0:
        return math.inf
    return math.sqrt(proportion * (1 - proportion) / observations)
