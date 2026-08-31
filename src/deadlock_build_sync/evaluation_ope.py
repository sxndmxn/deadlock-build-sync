from __future__ import annotations

import math
from dataclasses import dataclass

from .evaluation_core import (
    EvaluationError,
)


@dataclass(frozen=True)
class LoggedDecision:
    candidate_slate: tuple[str, ...]
    action: str
    behavior_propensity: float
    target_propensities: dict[str, float]
    outcome: float
    outcome_predictions: dict[str, float]

    def __post_init__(self) -> None:
        """Validate support, target probabilities, and outcome predictions.

        Raises:
            EvaluationError: If a logged decision cannot support OPE.

        """
        if not self.candidate_slate or len(self.candidate_slate) != len(
            set(self.candidate_slate)
        ):
            raise EvaluationError("logged candidate slate is empty or duplicated")
        if self.action not in self.candidate_slate or self.behavior_propensity <= 0:
            raise EvaluationError("logged action has no behavior support")
        if not 0 <= self.outcome <= 1:
            raise EvaluationError("logged outcome is outside [0, 1]")
        if set(self.target_propensities) != set(self.candidate_slate):
            raise EvaluationError("target policy must score the complete logged slate")
        if not math.isclose(sum(self.target_propensities.values()), 1.0, abs_tol=1e-9):
            raise EvaluationError("target propensities must sum to one")
        if any(value < 0 for value in self.target_propensities.values()):
            raise EvaluationError("target propensities cannot be negative")
        if set(self.outcome_predictions) != set(self.candidate_slate) or any(
            not 0 <= value <= 1 for value in self.outcome_predictions.values()
        ):
            raise EvaluationError("outcome model must score the complete logged slate")


@dataclass(frozen=True)
class OpeReport:
    supported: bool
    reason: str
    support: int
    overlap: float
    effective_sample_size: float
    maximum_weight: float
    ips: float | None
    self_normalized_ips: float | None
    doubly_robust: float | None
    clipped_sensitivity: dict[str, dict[str, float]]


def _ope_estimates(
    rows: list[LoggedDecision],
    *,
    clip: float | None,
) -> tuple[float, float, float, float, float]:
    weights = [
        min(row.target_propensities[row.action] / row.behavior_propensity, clip)
        if clip is not None
        else row.target_propensities[row.action] / row.behavior_propensity
        for row in rows
    ]
    ips = sum(
        weight * row.outcome for weight, row in zip(weights, rows, strict=True)
    ) / len(rows)
    total_weight = sum(weights)
    snips = (
        sum(weight * row.outcome for weight, row in zip(weights, rows, strict=True))
        / total_weight
        if total_weight
        else 0.0
    )
    dr_terms = []
    for weight, row in zip(weights, rows, strict=True):
        target_model = sum(
            probability * row.outcome_predictions[action]
            for action, probability in row.target_propensities.items()
        )
        dr_terms.append(
            target_model + weight * (row.outcome - row.outcome_predictions[row.action])
        )
    dr = sum(dr_terms) / len(dr_terms)
    squared_weight_sum = sum(weight**2 for weight in weights)
    ess = total_weight**2 / squared_weight_sum if squared_weight_sum else 0.0
    return ips, snips, dr, ess, max(weights, default=0.0)


def off_policy_evaluation(
    rows: list[LoggedDecision],
    *,
    clips: tuple[float, ...] = (5.0, 10.0, 20.0),
) -> OpeReport:
    """Run IPS, self-normalized IPS, DR, and clipping sensitivity diagnostics.

    Returns:
        Multiple estimators or an explicit no-support abstention.

    Raises:
        EvaluationError: If there are no logged decisions.

    """
    if not rows:
        raise EvaluationError("off-policy evaluation requires logged decisions")
    target_actions = {
        action
        for row in rows
        for action, probability in row.target_propensities.items()
        if probability > 0
    }
    observed_actions = {row.action for row in rows}
    unsupported = target_actions - observed_actions
    overlap = len(target_actions & observed_actions) / len(target_actions)
    if unsupported:
        return OpeReport(
            supported=False,
            reason="target actions outside logged support: "
            + ", ".join(sorted(unsupported)),
            support=len(rows),
            overlap=overlap,
            effective_sample_size=0.0,
            maximum_weight=0.0,
            ips=None,
            self_normalized_ips=None,
            doubly_robust=None,
            clipped_sensitivity={},
        )
    ips, snips, dr, ess, maximum = _ope_estimates(rows, clip=None)
    sensitivity = {}
    for clip in clips:
        clipped_ips, clipped_snips, clipped_dr, _, _ = _ope_estimates(rows, clip=clip)
        sensitivity[f"clip={clip:g}"] = {
            "ips": clipped_ips,
            "self_normalized_ips": clipped_snips,
            "doubly_robust": clipped_dr,
        }
    return OpeReport(
        supported=True,
        reason="all target actions have logged support",
        support=len(rows),
        overlap=overlap,
        effective_sample_size=ess,
        maximum_weight=maximum,
        ips=ips,
        self_normalized_ips=snips,
        doubly_robust=dr,
        clipped_sensitivity=sensitivity,
    )


PROHIBITED_DECISION_LOG_FIELDS = frozenset({
    "account_id",
    "steam_id",
    "player_id",
    "persona",
    "email",
    "ip_address",
})
