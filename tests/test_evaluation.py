import json
from dataclasses import replace
from pathlib import Path

import pytest

from deadlock_build_sync.evaluation import (
    HARD_GATE_LAYERS,
    REQUIRED_EVALUATION_LAYERS,
    CalibrationReport,
    EvaluationError,
    EvaluationLayer,
    EvaluationReport,
    Fold,
    LoggedDecision,
    MonitorAction,
    MonitoringSnapshot,
    PredictionRecord,
    RecommendationEvent,
    TargetTrialSpec,
    TemporalExample,
    calibration_report,
    evaluate_monitoring,
    off_policy_evaluation,
    patch_forward_group_split,
    select_abstention_threshold,
)


def layers(*, failed: str | None = None) -> tuple[EvaluationLayer, ...]:
    return tuple(
        EvaluationLayer(
            name,
            passed=name != failed,
            score=0.99 if name != failed else 0.0,
            support=100,
        )
        for name in REQUIRED_EVALUATION_LAYERS
    )


def test_evaluation_report_keeps_hard_gates_separate() -> None:
    report = EvaluationReport("snapshot", ("policy",), layers(), "split")
    assert report.passed
    assert report.hard_gates_passed
    assert set(HARD_GATE_LAYERS) == {
        layer.name for layer in report.layers if layer.hard_gate
    }

    failed = EvaluationReport(
        "snapshot",
        ("policy",),
        layers(failed="user_data_preservation"),
        "split",
    )
    assert not failed.passed
    assert not failed.hard_gates_passed
    assert failed.as_dict()["non_authoritative_minimum_score"] == 0.0


def temporal_examples() -> list[TemporalExample]:
    return [
        TemporalExample(1, 100, 90, "m1", "p1", "core"),
        TemporalExample(1, 100, 90, "m2", "p2", "core"),
        TemporalExample(2, 200, 190, "m3", "p3", "counter"),
        TemporalExample(3, 300, 290, "m4", "p4", "core"),
    ]


def test_patch_forward_split_is_chronological_group_safe_and_has_baseline() -> None:
    split = patch_forward_group_split(
        temporal_examples(),
        validation_patch=2,
        test_patch=3,
    )

    assert {row.patch_order for row in split.train} == {1}
    assert {row.patch_order for row in split.validation} == {2}
    assert {row.patch_order for row in split.test} == {3}
    assert split.popularity_baseline == "core"
    assert len(split.split_identity) == 64


@pytest.mark.parametrize("field", ["match_group", "player_group"])
def test_patch_forward_split_rejects_group_leakage(field: str) -> None:
    examples = temporal_examples()
    examples[2] = replace(examples[2], **{field: getattr(examples[0], field)})

    with pytest.raises(EvaluationError, match=field):
        patch_forward_group_split(examples, validation_patch=2, test_patch=3)


def test_temporal_example_rejects_future_features() -> None:
    with pytest.raises(EvaluationError, match="after the decision"):
        TemporalExample(1, 100, 101, "m", "p", "core")


def prediction(
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


def test_calibration_reports_brier_logloss_segments_and_selective_risk() -> None:
    report: CalibrationReport = calibration_report(
        [prediction(0.9, 1), prediction(0.1, 0), prediction(0.8, 0, hero_id=13)],
        threshold=0.85,
    )

    assert report.overall.support == 3
    assert report.overall.brier == pytest.approx(0.22)
    assert report.overall.log_loss > 0
    assert report.overall.coverage == pytest.approx(2 / 3)
    assert report.overall.selective_risk == 0
    assert {"hero=12", "hero=13", "mode=ranked", "rank=Mystic", "patch=patch-1"} <= set(
        report.by_segment
    )


def test_abstention_threshold_uses_validation_only() -> None:
    records = [prediction(0.9, 1), prediction(0.8, 1), prediction(0.55, 0)]

    threshold = select_abstention_threshold(records, maximum_risk=0.0)

    assert threshold == 0.6
    with pytest.raises(EvaluationError, match="validation only"):
        select_abstention_threshold(
            [prediction(0.9, 1, fold=Fold.TEST)],
            maximum_risk=0.1,
        )


def target_trial() -> TargetTrialSpec:
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


def test_target_trial_requires_save_sensitivity_and_overlap() -> None:
    trial = target_trial()
    assert trial.permits_causal_claim(0.25)
    assert not trial.permits_causal_claim(0.1)

    with pytest.raises(EvaluationError, match="save action"):
        replace(trial, treatments=("core", "counter"))


def logged(action: str, outcome: float) -> LoggedDecision:
    return LoggedDecision(
        candidate_slate=("core", "counter"),
        action=action,
        behavior_propensity=0.5,
        target_propensities={"core": 0.5, "counter": 0.5},
        outcome=outcome,
        outcome_predictions={"core": 1.0, "counter": 0.0},
    )


def test_off_policy_evaluation_recovers_known_policy_with_diagnostics() -> None:
    report = off_policy_evaluation([logged("core", 1), logged("counter", 0)] * 50)

    assert report.supported
    assert report.ips == pytest.approx(0.5)
    assert report.self_normalized_ips == pytest.approx(0.5)
    assert report.doubly_robust == pytest.approx(0.5)
    assert report.effective_sample_size == pytest.approx(100)
    assert set(report.clipped_sensitivity) == {"clip=5", "clip=10", "clip=20"}


def test_off_policy_evaluation_abstains_outside_logged_support() -> None:
    report = off_policy_evaluation([logged("core", 1)] * 10)

    assert not report.supported
    assert report.ips is None
    assert "counter" in report.reason


def event() -> RecommendationEvent:
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


def test_decision_log_round_trips_without_personal_fields() -> None:
    encoded = event().as_dict()

    decoded = RecommendationEvent.from_dict(encoded)

    assert decoded == event()
    assert not {
        "account_id",
        "steam_id",
        "player_id",
        "persona",
    } & set(encoded)


def test_decision_log_rejects_personal_fields_and_future_leakage() -> None:
    encoded = event().as_dict()
    encoded["steam_id"] = "not-allowed"
    with pytest.raises(EvaluationError, match="prohibited personal"):
        RecommendationEvent.from_dict(encoded)

    with pytest.raises(EvaluationError, match="future feature leakage"):
        replace(event(), feature_as_of_timestamp=201)


def monitor() -> MonitoringSnapshot:
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


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"mechanics_match": False}, "mechanics fingerprint"),
        ({"calibration_error": 0.2}, "calibration"),
        ({"schema_decode_ok": False}, "schema decode"),
        ({"preservation_unchanged": False}, "preservation"),
        ({"restore_failures": 1}, "restore failure"),
    ],
)
def test_monitoring_hard_failures_trigger_rollback(
    changes: dict[str, object],
    reason: str,
) -> None:
    decision = evaluate_monitoring(
        replace(monitor(), **changes),
        last_compatible_snapshot_id="last-snapshot",
        last_compatible_policy_ids=("last-policy",),
    )

    assert decision.action == MonitorAction.ROLLBACK
    assert decision.last_compatible_snapshot_id == "last-snapshot"
    assert any(reason in nested for nested in decision.reasons)


def test_monitoring_refuses_stale_or_rejected_policy_and_alerts_on_drift() -> None:
    refused = evaluate_monitoring(replace(monitor(), snapshot_age_s=90000))
    assert refused.action == MonitorAction.REFUSE

    alerted = evaluate_monitoring(
        replace(monitor(), unhandled_branches=5, recommendation_concentration=0.9)
    )
    assert alerted.action == MonitorAction.ALERT
    assert len(alerted.reasons) == 2

    assert evaluate_monitoring(monitor()).action == MonitorAction.HEALTHY


def test_checked_in_coverage_and_sample_report_are_complete() -> None:
    root = Path(__file__).resolve().parents[1]
    coverage = json.loads(
        (root / "docs/evaluation-coverage.json").read_text(encoding="utf-8")
    )
    required_scenarios = {
        "early_archetype",
        "midgame_archetype",
        "late_archetype",
        "weapon_variant",
        "spirit_variant",
        "vitality_variant",
        "hybrid_variant",
        "support_variant",
        "active_item_variant",
        "ahead_even_behind",
        "major_threat_classes",
        "sparse_cohort",
        "out_of_distribution_patch_or_hero",
        "component_event",
        "equal_time_event",
        "deviation",
        "missed_timing",
        "no_overlap_abstention",
        "slot_pressure",
        "active_binding_pressure",
        "flex_pressure",
        "incomplete_assets",
    }
    scenarios = coverage["scenarios"]
    assert required_scenarios <= set(scenarios)
    assert all(evidence for evidence in scenarios.values())
    assert all(
        (root / reference.split("::", maxsplit=1)[0]).is_file()
        for evidence in scenarios.values()
        for reference in evidence
    )

    sample = json.loads(
        (root / "docs/evaluation-sample-report.json").read_text(encoding="utf-8")
    )
    assert {layer["name"] for layer in sample["layers"]} == set(
        REQUIRED_EVALUATION_LAYERS
    )
    assert sample["hard_gates_passed"]
    assert not sample["passed"]
