"""Validated observational rate estimates."""

from dataclasses import dataclass

from .purchase_guide import wilson_score_interval
from .snapshot import EvidenceUnit


class TelemetryError(ValueError):
    """Raised when telemetry cannot support the declared estimand."""


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
