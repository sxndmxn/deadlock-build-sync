from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .snapshot import sha256_json


class EvaluationError(ValueError):
    """Raised when evaluation data, estimands, or monitoring state is invalid."""


REQUIRED_EVALUATION_LAYERS = (
    "mechanics_fidelity",
    "path_legality",
    "next_action_imitation",
    "probability_calibration",
    "selective_risk_coverage",
    "comparative_outcome_assumptions",
    "tactical_expert_review",
    "valve_round_trip",
    "user_data_preservation",
)
HARD_GATE_LAYERS = frozenset({
    "mechanics_fidelity",
    "path_legality",
    "valve_round_trip",
    "user_data_preservation",
})


@dataclass(frozen=True)
class EvaluationLayer:
    name: str
    passed: bool
    score: float | None
    support: int
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate the fixed layer taxonomy, score, and support.

        Raises:
            EvaluationError: If a layer field violates its contract.

        """
        if self.name not in REQUIRED_EVALUATION_LAYERS:
            raise EvaluationError(f"unknown evaluation layer {self.name}")
        if self.score is not None and not 0 <= self.score <= 1:
            raise EvaluationError(f"evaluation score for {self.name} is outside [0, 1]")
        if self.support < 0:
            raise EvaluationError(f"evaluation support for {self.name} is negative")

    @property
    def hard_gate(self) -> bool:
        """Whether failure blocks release regardless of recommendation scores."""
        return self.name in HARD_GATE_LAYERS

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "hard_gate": self.hard_gate,
            "score": self.score,
            "support": self.support,
            "details": self.details,
        }


@dataclass(frozen=True)
class EvaluationReport:
    snapshot_id: str
    policy_ids: tuple[str, ...]
    layers: tuple[EvaluationLayer, ...]
    split_identity: str

    def __post_init__(self) -> None:
        """Require complete identity and exactly one result per layer.

        Raises:
            EvaluationError: If identity or layer coverage is incomplete.

        """
        if (
            not self.snapshot_id.strip()
            or not self.policy_ids
            or not self.split_identity
        ):
            raise EvaluationError("evaluation report is missing identity")
        names = [layer.name for layer in self.layers]
        if len(names) != len(set(names)) or set(names) != set(
            REQUIRED_EVALUATION_LAYERS
        ):
            raise EvaluationError(
                "evaluation report must contain every layer exactly once"
            )

    @property
    def hard_gates_passed(self) -> bool:
        """Whether every mechanics, legality, round-trip, and preservation gate passed."""
        return all(layer.passed for layer in self.layers if layer.hard_gate)

    @property
    def passed(self) -> bool:
        """Whether every separately reported evaluation layer passed."""
        return self.hard_gates_passed and all(layer.passed for layer in self.layers)

    def as_dict(self) -> dict[str, Any]:
        scores = [layer.score for layer in self.layers if layer.score is not None]
        return {
            "schema_version": 1,
            "snapshot_id": self.snapshot_id,
            "policy_ids": list(self.policy_ids),
            "split_identity": self.split_identity,
            "passed": self.passed,
            "hard_gates_passed": self.hard_gates_passed,
            "non_authoritative_minimum_score": min(scores) if scores else None,
            "layers": [layer.as_dict() for layer in self.layers],
        }


class Fold(StrEnum):
    TRAIN = "train"
    VALIDATION = "validation"
    TEST = "test"


@dataclass(frozen=True)
class TemporalExample:
    patch_order: int
    decision_timestamp: int
    feature_as_of_timestamp: int
    match_group: str
    player_group: str
    action: str

    def __post_init__(self) -> None:
        """Reject future-derived features and missing group identities.

        Raises:
            EvaluationError: If temporal or grouping fields are invalid.

        """
        if self.feature_as_of_timestamp > self.decision_timestamp:
            raise EvaluationError("features were calculated after the decision")
        if not self.match_group or not self.player_group or not self.action:
            raise EvaluationError(
                "temporal example is missing group or action identity"
            )


@dataclass(frozen=True)
class ForwardSplit:
    train: tuple[TemporalExample, ...]
    validation: tuple[TemporalExample, ...]
    test: tuple[TemporalExample, ...]
    popularity_baseline: str

    @property
    def split_identity(self) -> str:
        return sha256_json({
            "train": [example.__dict__ for example in self.train],
            "validation": [example.__dict__ for example in self.validation],
            "test": [example.__dict__ for example in self.test],
            "popularity_baseline": self.popularity_baseline,
        })


def patch_forward_group_split(
    examples: list[TemporalExample],
    *,
    validation_patch: int,
    test_patch: int,
) -> ForwardSplit:
    """Create chronological folds and reject player or match leakage.

    Returns:
        Nonempty train, validation, and test folds plus the train popularity baseline.

    Raises:
        EvaluationError: If boundaries, folds, or group independence are invalid.

    """
    if validation_patch >= test_patch:
        raise EvaluationError("validation patch must precede test patch")
    train = tuple(row for row in examples if row.patch_order < validation_patch)
    validation = tuple(
        row for row in examples if validation_patch <= row.patch_order < test_patch
    )
    test = tuple(row for row in examples if row.patch_order >= test_patch)
    if not train or not validation or not test:
        raise EvaluationError("patch-forward split produced an empty fold")
    folds = (train, validation, test)
    for field_name in ("match_group", "player_group"):
        groups = [{getattr(example, field_name) for example in fold} for fold in folds]
        if any(
            groups[left] & groups[right]
            for left in range(3)
            for right in range(left + 1, 3)
        ):
            raise EvaluationError(f"{field_name} leaks across patch-forward folds")
    baseline = Counter(example.action for example in train).most_common(1)[0][0]
    return ForwardSplit(train, validation, test, baseline)


@dataclass(frozen=True)
class PredictionRecord:
    probability: float
    outcome: int
    fold: Fold
    match_mode: str
    rank: str
    hero_id: int
    patch: str

    def __post_init__(self) -> None:
        """Validate probability, outcome, and segment identity.

        Raises:
            EvaluationError: If a probability, outcome, or segment is invalid.

        """
        if not 0 <= self.probability <= 1 or self.outcome not in {0, 1}:
            raise EvaluationError("prediction probability or outcome is invalid")
        if not self.match_mode or not self.rank or not self.patch or self.hero_id <= 0:
            raise EvaluationError("prediction segment identity is incomplete")

    @property
    def confidence(self) -> float:
        """The predicted probability assigned to the selected binary class."""
        return max(self.probability, 1 - self.probability)

    @property
    def correct(self) -> bool:
        """Whether the thresholded binary prediction matches the outcome."""
        return (self.probability >= 0.5) == bool(self.outcome)


@dataclass(frozen=True)
class CalibrationSlice:
    support: int
    brier: float
    log_loss: float
    expected_calibration_error: float
    coverage: float
    selective_risk: float | None

    def as_dict(self) -> dict[str, int | float | None]:
        return self.__dict__


@dataclass(frozen=True)
class CalibrationReport:
    threshold: float
    overall: CalibrationSlice
    by_segment: dict[str, CalibrationSlice]


def _calibration_slice(
    records: list[PredictionRecord],
    *,
    threshold: float,
    bins: int = 10,
) -> CalibrationSlice:
    if not records:
        raise EvaluationError("calibration slice is empty")
    epsilon = 1e-15
    brier = sum((row.probability - row.outcome) ** 2 for row in records) / len(records)
    log_loss = -sum(
        row.outcome * math.log(max(row.probability, epsilon))
        + (1 - row.outcome) * math.log(max(1 - row.probability, epsilon))
        for row in records
    ) / len(records)
    bucketed: dict[int, list[PredictionRecord]] = defaultdict(list)
    for row in records:
        bucketed[min(int(row.probability * bins), bins - 1)].append(row)
    calibration_error = sum(
        len(bucket)
        / len(records)
        * abs(
            sum(row.probability for row in bucket) / len(bucket)
            - sum(row.outcome for row in bucket) / len(bucket)
        )
        for bucket in bucketed.values()
    )
    selected = [row for row in records if row.confidence >= threshold]
    risk = (
        sum(not row.correct for row in selected) / len(selected) if selected else None
    )
    return CalibrationSlice(
        support=len(records),
        brier=brier,
        log_loss=log_loss,
        expected_calibration_error=calibration_error,
        coverage=len(selected) / len(records),
        selective_risk=risk,
    )


def calibration_report(
    records: list[PredictionRecord],
    *,
    threshold: float,
) -> CalibrationReport:
    """Calculate calibration and selective risk overall and by cohort dimensions.

    Returns:
        Brier, log-loss, calibration, risk, and coverage metrics.

    Raises:
        EvaluationError: If the threshold or prediction population is invalid.

    """
    if not 0.5 <= threshold <= 1:
        raise EvaluationError("abstention threshold must be between 0.5 and 1")
    if not records:
        raise EvaluationError("calibration report requires predictions")
    groups: dict[str, list[PredictionRecord]] = defaultdict(list)
    for row in records:
        for label in (
            f"mode={row.match_mode}",
            f"rank={row.rank}",
            f"hero={row.hero_id}",
            f"patch={row.patch}",
        ):
            groups[label].append(row)
    return CalibrationReport(
        threshold,
        _calibration_slice(records, threshold=threshold),
        {
            name: _calibration_slice(group, threshold=threshold)
            for name, group in sorted(groups.items())
        },
    )


def select_abstention_threshold(
    validation_records: list[PredictionRecord],
    *,
    maximum_risk: float,
    candidates: tuple[float, ...] = (0.5, 0.6, 0.7, 0.8, 0.9),
) -> float:
    """Select the highest-coverage safe threshold on validation data only.

    Returns:
        The threshold with maximum coverage among candidates meeting the risk limit.

    Raises:
        EvaluationError: If test/train data is supplied or no candidate is safe.

    """
    if not validation_records or any(
        row.fold != Fold.VALIDATION for row in validation_records
    ):
        raise EvaluationError(
            "abstention threshold must be selected on validation only"
        )
    eligible: list[tuple[float, float]] = []
    for threshold in candidates:
        result = _calibration_slice(validation_records, threshold=threshold)
        if result.selective_risk is not None and result.selective_risk <= maximum_risk:
            eligible.append((result.coverage, threshold))
    if not eligible:
        raise EvaluationError("no validation threshold satisfies the risk limit")
    return max(eligible, key=lambda row: (row[0], -row[1]))[1]


@dataclass(frozen=True)
class TargetTrialSpec:
    name: str
    eligibility: str
    time_zero: str
    treatments: tuple[str, ...]
    assignment_model: str
    follow_up: str
    outcome: str
    censoring: str
    estimand: str
    sensitivity_analyses: tuple[str, ...]
    minimum_overlap: float = 0.1

    def __post_init__(self) -> None:
        """Require every target-trial field, save action, and sensitivity plan.

        Raises:
            EvaluationError: If the target trial cannot identify a causal estimand.

        """
        text = (
            self.name,
            self.eligibility,
            self.time_zero,
            self.assignment_model,
            self.follow_up,
            self.outcome,
            self.censoring,
            self.estimand,
        )
        if not all(value.strip() for value in text):
            raise EvaluationError("target trial is missing a required declaration")
        if len(self.treatments) < 2 or "save" not in {
            treatment.casefold() for treatment in self.treatments
        }:
            raise EvaluationError(
                "target trial treatments must include the save action"
            )
        if not self.sensitivity_analyses:
            raise EvaluationError("target trial requires sensitivity analysis")
        if not 0 < self.minimum_overlap <= 1:
            raise EvaluationError("target trial overlap threshold is invalid")

    def permits_causal_claim(self, observed_overlap: float) -> bool:
        """Check overlap against the predeclared causal threshold.

        Returns:
            Whether overlap permits the claim class to advance to causal.

        """
        return observed_overlap >= self.minimum_overlap


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
    ess = total_weight**2 / sum(weight**2 for weight in weights) if weights else 0.0
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

    def as_dict(self) -> dict[str, Any]:
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
    def from_dict(cls, value: dict[str, Any]) -> RecommendationEvent:
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
        try:
            raw_intermediate = value.get("intermediate_outcomes", {})
            if not isinstance(raw_intermediate, dict):
                raise EvaluationError("intermediate outcomes must be an object")
            return cls(
                decision_id=str(value["decision_id"]),
                snapshot_id=str(value["snapshot_id"]),
                policy_id=str(value["policy_id"]),
                recommendation_timestamp=int(value["recommendation_timestamp"]),
                feature_as_of_timestamp=int(value["feature_as_of_timestamp"]),
                candidate_order=tuple(str(item) for item in value["candidate_order"]),
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
                    float(value["behavior_propensity"])
                    if value.get("behavior_propensity") is not None
                    else None
                ),
                experiment_assignment=(
                    str(value["experiment_assignment"])
                    if value.get("experiment_assignment") is not None
                    else None
                ),
                intermediate_outcomes={
                    str(key): float(nested) for key, nested in raw_intermediate.items()
                },
                final_outcome=(
                    float(value["final_outcome"])
                    if value.get("final_outcome") is not None
                    else None
                ),
                retention_days=int(value.get("retention_days", 30)),
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
    rollback = []
    if not snapshot.mechanics_match:
        rollback.append("mechanics fingerprint mismatch")
    if snapshot.calibration_error > resolved.maximum_calibration_error:
        rollback.append("material calibration failure")
    if not snapshot.schema_decode_ok:
        rollback.append("schema decode failure")
    if not snapshot.preservation_unchanged:
        rollback.append("user-data preservation changed")
    if snapshot.restore_failures:
        rollback.append("restore failure")
    if rollback:
        if not last_compatible_snapshot_id or not last_compatible_policy_ids:
            rollback.append("no last compatible policy is available")
        return MonitoringDecision(
            MonitorAction.ROLLBACK,
            tuple(rollback),
            last_compatible_snapshot_id,
            last_compatible_policy_ids,
        )
    refusal = []
    if snapshot.snapshot_age_s > resolved.maximum_snapshot_age_s:
        refusal.append("snapshot freshness exceeded")
    if snapshot.path_rejections or snapshot.render_rejections:
        refusal.append("path or render rejection observed")
    if snapshot.install_failures:
        refusal.append("install failure observed")
    if refusal:
        return MonitoringDecision(
            MonitorAction.REFUSE,
            tuple(refusal),
            last_compatible_snapshot_id,
            last_compatible_policy_ids,
        )
    alert = []
    if snapshot.invalid_state_rate > resolved.maximum_invalid_state_rate:
        alert.append("invalid-state rate exceeded")
    branch_rate = (
        snapshot.unhandled_branches / snapshot.exposures if snapshot.exposures else 0.0
    )
    if branch_rate > resolved.maximum_unhandled_branch_rate:
        alert.append("unhandled-branch rate exceeded")
    if snapshot.recommendation_concentration > resolved.maximum_concentration:
        alert.append("recommendation concentration exceeded")
    return MonitoringDecision(
        MonitorAction.ALERT if alert else MonitorAction.HEALTHY,
        tuple(alert),
        last_compatible_snapshot_id,
        last_compatible_policy_ids,
    )
