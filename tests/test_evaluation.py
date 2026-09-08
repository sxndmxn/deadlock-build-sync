import json
from dataclasses import asdict, replace
from pathlib import Path

import pytest

from deadlock_build_sync.evaluation import (
    HARD_GATE_LAYERS,
    REQUIRED_EVALUATION_LAYERS,
    CalibrationReport,
    EvaluationError,
    EvaluationReport,
    Fold,
    MonitorAction,
    RecommendationEvent,
    TemporalExample,
    calibration_report,
    evaluate_monitoring,
    off_policy_evaluation,
    patch_forward_group_split,
    select_abstention_threshold,
)
from deadlock_build_sync.offline.config import sha256_json
from tests.evaluation_fixtures import (
    make_evaluation_layers,
    make_logged_decision,
    make_monitoring_snapshot,
    make_prediction,
    make_recommendation_event,
    make_target_trial,
    make_temporal_examples,
)


def test_evaluation_report_keeps_hard_gates_separate() -> None:
    report = EvaluationReport(
        "snapshot", ("policy",), make_evaluation_layers(), "split"
    )
    assert report.passed
    assert report.hard_gates_passed
    assert set(HARD_GATE_LAYERS) == {
        layer.name for layer in report.layers if layer.hard_gate
    }

    failed = EvaluationReport(
        "snapshot",
        ("policy",),
        make_evaluation_layers(failed="user_data_preservation"),
        "split",
    )
    assert not failed.passed
    assert not failed.hard_gates_passed
    assert failed.as_dict()["non_authoritative_minimum_score"] == 0.0


def test_patch_forward_split_is_chronological_group_safe_and_has_baseline() -> None:
    split = patch_forward_group_split(
        make_temporal_examples(),
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
    examples = make_temporal_examples()
    examples[2] = replace(examples[2], **{field: getattr(examples[0], field)})

    with pytest.raises(EvaluationError, match=field):
        patch_forward_group_split(examples, validation_patch=2, test_patch=3)


def test_temporal_example_rejects_future_features() -> None:
    with pytest.raises(EvaluationError, match="after the decision"):
        TemporalExample(1, 100, 101, "m", "p", "core")


def test_calibration_reports_brier_logloss_segments_and_selective_risk() -> None:
    report: CalibrationReport = calibration_report(
        [
            make_prediction(0.9, 1),
            make_prediction(0.1, 0),
            make_prediction(0.8, 0, hero_id=13),
        ],
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
    records = [
        make_prediction(0.9, 1),
        make_prediction(0.8, 1),
        make_prediction(0.55, 0),
    ]

    threshold = select_abstention_threshold(records, maximum_risk=0.0)

    assert threshold == 0.6
    test_records = [make_prediction(0.9, 1, fold=Fold.TEST)]
    with pytest.raises(EvaluationError, match="validation only"):
        select_abstention_threshold(test_records, maximum_risk=0.1)


def test_target_trial_requires_save_sensitivity_and_overlap() -> None:
    trial = make_target_trial()
    assert trial.permits_causal_claim(0.25)
    assert not trial.permits_causal_claim(0.1)

    with pytest.raises(EvaluationError, match="save action"):
        replace(trial, treatments=("core", "counter"))


def test_off_policy_evaluation_recovers_known_policy_with_diagnostics() -> None:
    report = off_policy_evaluation(
        [make_logged_decision("core", 1), make_logged_decision("counter", 0)] * 50
    )

    assert report.supported
    assert report.ips == pytest.approx(0.5)
    assert report.self_normalized_ips == pytest.approx(0.5)
    assert report.doubly_robust == pytest.approx(0.5)
    assert report.effective_sample_size == pytest.approx(100)
    assert report.maximum_weight == pytest.approx(1)
    assert set(report.clipped_sensitivity) == {"clip=5", "clip=10", "clip=20"}
    assert sha256_json(asdict(report)) == (
        "a030c0af52696c89cadcf2f55149993e37a3a2f42ad79c96c1067bc7baeb006d"
    )


def test_off_policy_evaluation_abstains_outside_logged_support() -> None:
    report = off_policy_evaluation([make_logged_decision("core", 1)] * 10)

    assert not report.supported
    assert report.ips is None
    assert "counter" in report.reason


def test_decision_log_round_trips_without_personal_fields() -> None:
    encoded = make_recommendation_event().as_dict()

    decoded = RecommendationEvent.from_dict(encoded)

    assert decoded == make_recommendation_event()
    assert not {
        "account_id",
        "steam_id",
        "player_id",
        "persona",
    } & set(encoded)


def test_decision_log_rejects_personal_fields_and_future_leakage() -> None:
    encoded = make_recommendation_event().as_dict()
    encoded["steam_id"] = "not-allowed"
    with pytest.raises(EvaluationError, match="prohibited personal"):
        RecommendationEvent.from_dict(encoded)

    source = make_recommendation_event()
    with pytest.raises(EvaluationError, match="future feature leakage"):
        replace(source, feature_as_of_timestamp=201)


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
        replace(make_monitoring_snapshot(), **changes),
        last_compatible_snapshot_id="last-snapshot",
        last_compatible_policy_ids=("last-policy",),
    )

    assert decision.action == MonitorAction.ROLLBACK
    assert decision.last_compatible_snapshot_id == "last-snapshot"
    assert any(reason in nested for nested in decision.reasons)


def test_monitoring_refuses_stale_or_rejected_policy_and_alerts_on_drift() -> None:
    refused = evaluate_monitoring(
        replace(make_monitoring_snapshot(), snapshot_age_s=90000)
    )
    assert refused.action == MonitorAction.REFUSE

    alerted = evaluate_monitoring(
        replace(
            make_monitoring_snapshot(),
            unhandled_branches=5,
            recommendation_concentration=0.9,
        )
    )
    assert alerted.action == MonitorAction.ALERT
    assert len(alerted.reasons) == 2

    assert (
        evaluate_monitoring(make_monitoring_snapshot()).action == MonitorAction.HEALTHY
    )


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
