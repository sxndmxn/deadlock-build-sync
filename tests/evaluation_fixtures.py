"""Independent records for evaluation tests."""

from deadlock_build_sync.evaluation import (
    REQUIRED_EVALUATION_LAYERS,
    EvaluationLayer,
    Fold,
    LoggedDecision,
    MonitoringSnapshot,
    PredictionRecord,
    RecommendationEvent,
    TargetTrialSpec,
    TemporalExample,
)


def make_evaluation_layers(*, failed: str | None = None) -> tuple[EvaluationLayer, ...]:
    return tuple(
        EvaluationLayer(
            name,
            passed=name != failed,
            score=0.99 if name != failed else 0.0,
            support=100,
        )
        for name in REQUIRED_EVALUATION_LAYERS
    )


def make_temporal_examples() -> list[TemporalExample]:
    return [
        TemporalExample(1, 100, 90, "m1", "p1", "core"),
        TemporalExample(1, 100, 90, "m2", "p2", "core"),
        TemporalExample(2, 200, 190, "m3", "p3", "counter"),
        TemporalExample(3, 300, 290, "m4", "p4", "core"),
    ]


def make_prediction(
    probability: float,
    outcome: int,
    *,
    fold: Fold = Fold.VALIDATION,
    hero_id: int = 12,
) -> PredictionRecord:
    return PredictionRecord(
        probability,
        outcome,
        fold,
        "ranked",
        "Mystic",
        hero_id,
        "patch-1",
    )


def make_target_trial() -> TargetTrialSpec:
    return TargetTrialSpec(
        name="first Tier II decision",
        eligibility="eligible ranked player-match at the decision landmark",
        time_zero="first legal Tier II shop decision",
        treatments=("core", "counter", "save"),
        assignment_model="multinomial propensity over the candidate slate",
        follow_up="until match end",
        outcome="predeclared objective conversion and final outcome",
        censoring="disconnect, invalid outcome, or telemetry loss",
        estimand="eligible-decision average treatment effect",
        sensitivity_analyses=("unmeasured confounding", "propensity clipping"),
        minimum_overlap=0.2,
    )


def make_logged_decision(action: str, outcome: float) -> LoggedDecision:
    return LoggedDecision(
        candidate_slate=("core", "counter"),
        action=action,
        behavior_propensity=0.5,
        target_propensities={"core": 0.5, "counter": 0.5},
        outcome=outcome,
        outcome_predictions={"core": 1.0, "counter": 0.0},
    )


def make_recommendation_event() -> RecommendationEvent:
    return RecommendationEvent(
        decision_id="decision-1",
        snapshot_id="snapshot",
        policy_id="policy",
        recommendation_timestamp=200,
        feature_as_of_timestamp=199,
        candidate_order=("core", "counter", "save"),
        exposed=True,
        recommendation="core",
        adopted_action="counter",
        deviation_reason="observed threat",
        recalculation_node="counter-check",
        behavior_propensity=0.5,
        experiment_assignment=None,
        intermediate_outcomes={"objective_conversion": 1.0},
        final_outcome=1.0,
    )


def make_monitoring_snapshot() -> MonitoringSnapshot:
    return MonitoringSnapshot(
        snapshot_age_s=100,
        invalid_state_rate=0.0,
        exposures=100,
        adoptions=80,
        deviations=10,
        unhandled_branches=0,
        calibration_error=0.02,
        recommendation_concentration=0.5,
        path_rejections=0,
        render_rejections=0,
        artifact_reuses=90,
        artifact_requests=100,
        install_failures=0,
        restore_failures=0,
        mechanics_match=True,
        schema_decode_ok=True,
        preservation_unchanged=True,
    )
