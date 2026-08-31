from __future__ import annotations

import math
import operator
from collections import Counter, defaultdict
from dataclasses import dataclass
from enum import StrEnum

from .purchase_guide import wilson_score_interval
from .snapshot import MatchMode
from .telemetry_rates import TelemetryError, empirical_bayes_rate
from .value_validation import integer

EARLY_NET_WORTH_CUTOFF_S = 180
MAX_PRECEDING_NET_WORTH_AGE_S = 60


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
    rows: list[dict[str, object]],
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
        matches = integer(row.get("matches"), default=0)
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
    value: object
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
