from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from enum import StrEnum

from .mechanics import ItemGraph, MechanicsError
from .purchase_guide import wilson_score_interval
from .snapshot import EvidenceUnit, OutcomePolicy
from .telemetry_analysis import (
    AbilityDecision,
    AbilityDecisionReport,
    CandidateEffect,
    CohortWindow,
    LandmarkEstimate,
    LandmarkObservation,
    MatchupEstimate,
    MatchupPair,
    MatchupScope,
    StateFeature,
    aggregate_ability_prefixes,
    bonferroni_alpha,
    effective_support,
    estimate_landmarks,
    estimate_matchups,
    select_then_estimate,
    standard_error,
    widen_sparse_cohort,
)
from .telemetry_rates import (
    RateEstimate,
    TelemetryError,
    descriptive_rate,
    empirical_bayes_rate,
)

EARLY_NET_WORTH_CUTOFF_S = 180
MAX_PRECEDING_NET_WORTH_AGE_S = 60


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


__all__ = [
    "AbilityDecision",
    "AbilityDecisionReport",
    "AdoptionEstimate",
    "CandidateEffect",
    "CohortWindow",
    "CompetingEvent",
    "FirstPurchaseObservation",
    "HazardPoint",
    "InventoryEvent",
    "InventoryEventKind",
    "LandmarkEstimate",
    "LandmarkObservation",
    "MatchupEstimate",
    "MatchupPair",
    "MatchupScope",
    "OutcomeRow",
    "PurchaseEvent",
    "RateEstimate",
    "ReconstructedEvent",
    "StateFeature",
    "TelemetryError",
    "aggregate_ability_prefixes",
    "bonferroni_alpha",
    "descriptive_rate",
    "effective_support",
    "empirical_bayes_rate",
    "estimate_item_adoption",
    "estimate_landmarks",
    "estimate_matchups",
    "first_purchase_cumulative_incidence",
    "outcome_is_eligible",
    "reconstruct_inventory_events",
    "select_then_estimate",
    "standard_error",
    "validated_purchase_net_worth",
    "widen_sparse_cohort",
]
