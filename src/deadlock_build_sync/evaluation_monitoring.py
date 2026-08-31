from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .evaluation_core import (
    EvaluationError,
)
from .evaluation_ope import PROHIBITED_DECISION_LOG_FIELDS
from .value_validation import integer, number, object_dict, object_list


@dataclass(frozen=True)
class RecommendationEvent:
    decision_id: str
    snapshot_id: str
    policy_id: str
    recommendation_timestamp: int
    feature_as_of_timestamp: int
    candidate_order: tuple[str, ...]
    exposed: bool
    recommendation: str
    adopted_action: str | None
    deviation_reason: str | None
    recalculation_node: str | None
    behavior_propensity: float | None
    experiment_assignment: str | None
    intermediate_outcomes: dict[str, float]
    final_outcome: float | None
    retention_days: int = 30

    def __post_init__(self) -> None:
        """Validate privacy, timing, exposure, outcome, and retention constraints.

        Raises:
            EvaluationError: If a recommendation event violates the log contract.

        """
        if not self.decision_id or not self.snapshot_id or not self.policy_id:
            raise EvaluationError("decision log identity is incomplete")
        if self.feature_as_of_timestamp > self.recommendation_timestamp:
            raise EvaluationError("decision log contains future feature leakage")
        if not self.candidate_order or len(self.candidate_order) != len(
            set(self.candidate_order)
        ):
            raise EvaluationError("decision log candidate order is invalid")
        if self.recommendation not in self.candidate_order:
            raise EvaluationError(
                "recommendation is outside the logged candidate slate"
            )
        if (
            self.adopted_action is not None
            and self.adopted_action not in self.candidate_order
        ):
            raise EvaluationError(
                "adopted action is outside the logged candidate slate"
            )
        if (
            self.exposed
            and self.behavior_propensity is None
            and not self.experiment_assignment
        ):
            raise EvaluationError("exposure needs propensity or experiment assignment")
        if (
            self.behavior_propensity is not None
            and not 0 < self.behavior_propensity <= 1
        ):
            raise EvaluationError("decision-log propensity is invalid")
        outcomes = [*self.intermediate_outcomes.values()]
        if self.final_outcome is not None:
            outcomes.append(self.final_outcome)
        if any(not 0 <= value <= 1 for value in outcomes):
            raise EvaluationError("decision-log outcome is outside [0, 1]")
        if not 1 <= self.retention_days <= 90:
            raise EvaluationError(
                "decision-log retention must be between 1 and 90 days"
            )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "decision_id": self.decision_id,
            "snapshot_id": self.snapshot_id,
            "policy_id": self.policy_id,
            "recommendation_timestamp": self.recommendation_timestamp,
            "feature_as_of_timestamp": self.feature_as_of_timestamp,
            "candidate_order": list(self.candidate_order),
            "exposed": self.exposed,
            "recommendation": self.recommendation,
            "adopted_action": self.adopted_action,
            "deviation_reason": self.deviation_reason,
            "recalculation_node": self.recalculation_node,
            "behavior_propensity": self.behavior_propensity,
            "experiment_assignment": self.experiment_assignment,
            "intermediate_outcomes": self.intermediate_outcomes,
            "final_outcome": self.final_outcome,
            "retention_days": self.retention_days,
        }

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> RecommendationEvent:
        """Decode a privacy-bounded event and reject prohibited identity fields.

        Returns:
            A validated recommendation event.

        Raises:
            EvaluationError: If schema, privacy, timing, or exposure fields are invalid.

        """
        prohibited = set(value) & PROHIBITED_DECISION_LOG_FIELDS
        if prohibited:
            raise EvaluationError(
                "decision log contains prohibited personal fields: "
                + ", ".join(sorted(prohibited))
            )
        if value.get("schema_version") != 1:
            raise EvaluationError("unsupported decision-log schema")
        raw_intermediate = object_dict(value.get("intermediate_outcomes", {}))
        if raw_intermediate is None:
            raise EvaluationError("intermediate outcomes must be an object")
        candidate_order = object_list(value.get("candidate_order"))
        if candidate_order is None:
            raise EvaluationError("candidate order must be an array")
        try:
            return cls(
                decision_id=str(value["decision_id"]),
                snapshot_id=str(value["snapshot_id"]),
                policy_id=str(value["policy_id"]),
                recommendation_timestamp=integer(value["recommendation_timestamp"]),
                feature_as_of_timestamp=integer(value["feature_as_of_timestamp"]),
                candidate_order=tuple(str(item) for item in candidate_order),
                exposed=bool(value["exposed"]),
                recommendation=str(value["recommendation"]),
                adopted_action=(
                    str(value["adopted_action"])
                    if value.get("adopted_action") is not None
                    else None
                ),
                deviation_reason=(
                    str(value["deviation_reason"])
                    if value.get("deviation_reason") is not None
                    else None
                ),
                recalculation_node=(
                    str(value["recalculation_node"])
                    if value.get("recalculation_node") is not None
                    else None
                ),
                behavior_propensity=(
                    number(value["behavior_propensity"])
                    if value.get("behavior_propensity") is not None
                    else None
                ),
                experiment_assignment=(
                    str(value["experiment_assignment"])
                    if value.get("experiment_assignment") is not None
                    else None
                ),
                intermediate_outcomes={
                    str(key): number(nested) for key, nested in raw_intermediate.items()
                },
                final_outcome=(
                    number(value["final_outcome"])
                    if value.get("final_outcome") is not None
                    else None
                ),
                retention_days=integer(value.get("retention_days"), default=30),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise EvaluationError(f"malformed decision log: {error}") from error


class MonitorAction(StrEnum):
    HEALTHY = "healthy"
    ALERT = "alert"
    REFUSE = "refuse_new_policy"
    ROLLBACK = "rollback"


@dataclass(frozen=True)
class MonitoringSnapshot:
    snapshot_age_s: int
    invalid_state_rate: float
    exposures: int
    adoptions: int
    deviations: int
    unhandled_branches: int
    calibration_error: float
    recommendation_concentration: float
    path_rejections: int
    render_rejections: int
    artifact_reuses: int
    artifact_requests: int
    install_failures: int
    restore_failures: int
    mechanics_match: bool
    schema_decode_ok: bool
    preservation_unchanged: bool

    def __post_init__(self) -> None:
        """Validate monitoring rates, event counts, and accounting identities.

        Raises:
            EvaluationError: If monitoring values are impossible or out of range.

        """
        rates = (
            self.invalid_state_rate,
            self.calibration_error,
            self.recommendation_concentration,
        )
        counts = (
            self.snapshot_age_s,
            self.exposures,
            self.adoptions,
            self.deviations,
            self.unhandled_branches,
            self.path_rejections,
            self.render_rejections,
            self.artifact_reuses,
            self.artifact_requests,
            self.install_failures,
            self.restore_failures,
        )
        if any(not 0 <= value <= 1 for value in rates) or any(
            value < 0 for value in counts
        ):
            raise EvaluationError("monitoring snapshot contains invalid values")
        if self.adoptions + self.deviations > self.exposures:
            raise EvaluationError("monitoring decisions exceed exposures")
        if self.artifact_reuses > self.artifact_requests:
            raise EvaluationError("artifact reuses exceed requests")


@dataclass(frozen=True)
class MonitoringThresholds:
    maximum_snapshot_age_s: int = 86400
    maximum_invalid_state_rate: float = 0.01
    maximum_calibration_error: float = 0.1
    maximum_concentration: float = 0.8
    maximum_unhandled_branch_rate: float = 0.01


@dataclass(frozen=True)
class MonitoringDecision:
    action: MonitorAction
    reasons: tuple[str, ...]
    last_compatible_snapshot_id: str | None
    last_compatible_policy_ids: tuple[str, ...]


def _rollback_reasons(
    snapshot: MonitoringSnapshot,
    thresholds: MonitoringThresholds,
) -> list[str]:
    reasons = []
    if not snapshot.mechanics_match:
        reasons.append("mechanics fingerprint mismatch")
    if snapshot.calibration_error > thresholds.maximum_calibration_error:
        reasons.append("material calibration failure")
    if not snapshot.schema_decode_ok:
        reasons.append("schema decode failure")
    if not snapshot.preservation_unchanged:
        reasons.append("user-data preservation changed")
    if snapshot.restore_failures:
        reasons.append("restore failure")
    return reasons


def _refusal_reasons(
    snapshot: MonitoringSnapshot,
    thresholds: MonitoringThresholds,
) -> list[str]:
    reasons = []
    if snapshot.snapshot_age_s > thresholds.maximum_snapshot_age_s:
        reasons.append("snapshot freshness exceeded")
    if snapshot.path_rejections or snapshot.render_rejections:
        reasons.append("path or render rejection observed")
    if snapshot.install_failures:
        reasons.append("install failure observed")
    return reasons


def _alert_reasons(
    snapshot: MonitoringSnapshot,
    thresholds: MonitoringThresholds,
) -> list[str]:
    reasons = []
    if snapshot.invalid_state_rate > thresholds.maximum_invalid_state_rate:
        reasons.append("invalid-state rate exceeded")
    branch_rate = (
        snapshot.unhandled_branches / snapshot.exposures if snapshot.exposures else 0.0
    )
    if branch_rate > thresholds.maximum_unhandled_branch_rate:
        reasons.append("unhandled-branch rate exceeded")
    if snapshot.recommendation_concentration > thresholds.maximum_concentration:
        reasons.append("recommendation concentration exceeded")
    return reasons


def evaluate_monitoring(
    snapshot: MonitoringSnapshot,
    *,
    thresholds: MonitoringThresholds | None = None,
    last_compatible_snapshot_id: str | None = None,
    last_compatible_policy_ids: tuple[str, ...] = (),
) -> MonitoringDecision:
    """Evaluate freshness, validity, feedback, rendering, and mutation rollback rules.

    Returns:
        The strongest required action with every triggering reason.

    """
    resolved = thresholds or MonitoringThresholds()
    rollback = _rollback_reasons(snapshot, resolved)
    if rollback:
        if not last_compatible_snapshot_id or not last_compatible_policy_ids:
            rollback.append("no last compatible policy is available")
        return MonitoringDecision(
            MonitorAction.ROLLBACK,
            tuple(rollback),
            last_compatible_snapshot_id,
            last_compatible_policy_ids,
        )
    refusal = _refusal_reasons(snapshot, resolved)
    if refusal:
        return MonitoringDecision(
            MonitorAction.REFUSE,
            tuple(refusal),
            last_compatible_snapshot_id,
            last_compatible_policy_ids,
        )
    alert = _alert_reasons(snapshot, resolved)
    return MonitoringDecision(
        MonitorAction.ALERT if alert else MonitorAction.HEALTHY,
        tuple(alert),
        last_compatible_snapshot_id,
        last_compatible_policy_ids,
    )
