from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from enum import StrEnum

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
    details: dict[str, object] = field(default_factory=dict)

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

    def as_dict(self) -> dict[str, object]:
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

    def as_dict(self) -> dict[str, object]:
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


def _calculate_calibration_slice(
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
        _calculate_calibration_slice(records, threshold=threshold),
        {
            name: _calculate_calibration_slice(group, threshold=threshold)
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
        result = _calculate_calibration_slice(validation_records, threshold=threshold)
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
