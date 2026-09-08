from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from deadlock_build_sync import evaluation_core, evaluation_ope
from deadlock_build_sync.evaluation import (
    REQUIRED_EVALUATION_LAYERS,
    EvaluationError,
    EvaluationLayer,
    EvaluationReport,
    Fold,
    LoggedDecision,
    MonitorAction,
    PredictionRecord,
    RecommendationEvent,
    TemporalExample,
    calibration_report,
    evaluate_monitoring,
    off_policy_evaluation,
    patch_forward_group_split,
    select_abstention_threshold,
)
from tests.evaluation_fixtures import (
    event,
    layers,
    monitor,
    prediction,
    target_trial,
)

if TYPE_CHECKING:
    from collections.abc import Callable


@pytest.mark.parametrize(
    "layer",
    [
        lambda: EvaluationLayer("unknown", passed=True, score=1.0, support=1),
        lambda: EvaluationLayer(
            REQUIRED_EVALUATION_LAYERS[0],
            passed=True,
            score=2.0,
            support=1,
        ),
        lambda: EvaluationLayer(
            REQUIRED_EVALUATION_LAYERS[0],
            passed=True,
            score=1.0,
            support=-1,
        ),
    ],
)
def test_evaluation_layer_rejects_invalid_taxonomy_score_and_support(
    layer: Callable[[], EvaluationLayer],
) -> None:
    with pytest.raises(EvaluationError):
        layer()


def test_evaluation_report_rejects_identity_and_layer_coverage() -> None:
    with pytest.raises(EvaluationError, match="missing identity"):
        EvaluationReport("", ("policy",), layers(), "split")
    with pytest.raises(EvaluationError, match="every layer"):
        EvaluationReport("snapshot", ("policy",), layers()[:-1], "split")

    no_scores = tuple(replace(layer, score=None) for layer in layers())
    report = EvaluationReport("snapshot", ("policy",), no_scores, "split")
    assert report.as_dict()["non_authoritative_minimum_score"] is None


def test_temporal_examples_and_split_reject_missing_identity_and_bad_folds() -> None:
    with pytest.raises(EvaluationError, match="group or action"):
        TemporalExample(1, 1, 1, "", "player", "action")
    with pytest.raises(EvaluationError, match="must precede"):
        patch_forward_group_split([], validation_patch=2, test_patch=2)
    with pytest.raises(EvaluationError, match="empty fold"):
        patch_forward_group_split(
            [TemporalExample(1, 1, 1, "match", "player", "action")],
            validation_patch=2,
            test_patch=3,
        )


@pytest.mark.parametrize(
    "record",
    [
        lambda: PredictionRecord(2.0, 1, Fold.TEST, "ranked", "rank", 1, "patch"),
        lambda: PredictionRecord(0.5, 2, Fold.TEST, "ranked", "rank", 1, "patch"),
        lambda: PredictionRecord(0.5, 1, Fold.TEST, "", "rank", 1, "patch"),
    ],
)
def test_prediction_record_rejects_invalid_probability_outcome_and_identity(
    record: Callable[[], PredictionRecord],
) -> None:
    with pytest.raises(EvaluationError):
        record()


def test_calibration_rejects_empty_inputs_and_supports_full_abstention() -> None:
    with pytest.raises(EvaluationError, match="slice is empty"):
        evaluation_core._calibration_slice([], threshold=0.5)
    with pytest.raises(EvaluationError, match=r"between 0.5 and 1"):
        calibration_report([prediction(0.5, 1)], threshold=0.4)
    with pytest.raises(EvaluationError, match="requires predictions"):
        calibration_report([], threshold=0.5)

    result = evaluation_core._calibration_slice(
        [prediction(0.6, 1), prediction(0.4, 0)],
        threshold=1.0,
    )
    assert result.coverage == 0.0
    assert result.selective_risk is None


def test_threshold_selection_rejects_empty_and_unsafe_candidates() -> None:
    with pytest.raises(EvaluationError, match="validation only"):
        select_abstention_threshold([], maximum_risk=0.1)
    with pytest.raises(EvaluationError, match="no validation threshold"):
        select_abstention_threshold(
            [prediction(0.9, 0)],
            maximum_risk=-1.0,
            candidates=(0.5,),
        )


def test_target_trial_rejects_missing_text_sensitivity_and_overlap() -> None:
    trial = target_trial()
    with pytest.raises(EvaluationError, match="required declaration"):
        replace(trial, name="")
    with pytest.raises(EvaluationError, match="sensitivity"):
        replace(trial, sensitivity_analyses=())
    with pytest.raises(EvaluationError, match="overlap threshold"):
        replace(trial, minimum_overlap=0.0)


@pytest.mark.parametrize(
    "decision",
    [
        lambda: LoggedDecision((), "core", 0.5, {}, 1.0, {}),
        lambda: LoggedDecision(
            ("core", "core"), "core", 0.5, {"core": 1.0}, 1.0, {"core": 1.0}
        ),
        lambda: LoggedDecision(
            ("core",), "other", 0.5, {"core": 1.0}, 1.0, {"core": 1.0}
        ),
        lambda: LoggedDecision(
            ("core",), "core", 0.0, {"core": 1.0}, 1.0, {"core": 1.0}
        ),
        lambda: LoggedDecision(
            ("core",), "core", 0.5, {"core": 1.0}, 2.0, {"core": 1.0}
        ),
        lambda: LoggedDecision(("core",), "core", 0.5, {}, 1.0, {"core": 1.0}),
        lambda: LoggedDecision(
            ("core",), "core", 0.5, {"core": 0.5}, 1.0, {"core": 1.0}
        ),
        lambda: LoggedDecision(
            ("core", "save"),
            "core",
            0.5,
            {"core": 1.1, "save": -0.1},
            1.0,
            {"core": 1.0, "save": 0.0},
        ),
        lambda: LoggedDecision(("core",), "core", 0.5, {"core": 1.0}, 1.0, {}),
        lambda: LoggedDecision(
            ("core",), "core", 0.5, {"core": 1.0}, 1.0, {"core": 2.0}
        ),
    ],
)
def test_logged_decision_rejects_each_support_and_model_error(
    decision: Callable[[], LoggedDecision],
) -> None:
    with pytest.raises(EvaluationError):
        decision()


def test_ope_handles_zero_target_weight_and_empty_population() -> None:
    zero_weight = LoggedDecision(
        ("core", "save"),
        "core",
        0.5,
        {"core": 0.0, "save": 1.0},
        1.0,
        {"core": 1.0, "save": 0.0},
    )
    estimates = evaluation_ope._ope_estimates([zero_weight], clip=None)
    assert estimates[1] == 0.0
    with pytest.raises(EvaluationError, match="requires logged decisions"):
        off_policy_evaluation([])


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"decision_id": ""}, "identity"),
        ({"candidate_order": ()}, "candidate order"),
        ({"candidate_order": ("core", "core")}, "candidate order"),
        ({"recommendation": "other"}, "outside"),
        ({"adopted_action": "other"}, "outside"),
        ({"behavior_propensity": None, "experiment_assignment": None}, "exposure"),
        ({"behavior_propensity": 0.0}, "propensity"),
        ({"intermediate_outcomes": {"objective": 2.0}}, "outcome"),
        ({"retention_days": 0}, "retention"),
    ],
)
def test_recommendation_event_rejects_invalid_contract_fields(
    changes: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(EvaluationError, match=message):
        replace(event(), **changes)


def test_recommendation_event_accepts_experiment_and_absent_optional_values() -> None:
    source = replace(
        event(),
        adopted_action=None,
        deviation_reason=None,
        recalculation_node=None,
        behavior_propensity=None,
        experiment_assignment="experiment-a",
        final_outcome=None,
    )
    assert RecommendationEvent.from_dict(source.as_dict()) == source


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"schema_version": 0}, "unsupported"),
        ({"intermediate_outcomes": []}, "must be an object"),
        ({"candidate_order": {}}, "must be an array"),
        ({"decision_id": None}, "malformed"),
    ],
)
def test_recommendation_event_decoder_rejects_bad_shapes(
    change: dict[str, object],
    message: str,
) -> None:
    encoded = event().as_dict()
    encoded.update(change)
    if change == {"decision_id": None}:
        encoded.pop("decision_id")
    with pytest.raises(EvaluationError, match=message):
        RecommendationEvent.from_dict(encoded)


@pytest.mark.parametrize(
    "changes",
    [
        {"invalid_state_rate": 2.0},
        {"exposures": -1},
        {"adoptions": 95, "deviations": 10},
        {"artifact_reuses": 101},
    ],
)
def test_monitoring_snapshot_rejects_invalid_rates_counts_and_accounting(
    changes: dict[str, object],
) -> None:
    with pytest.raises(EvaluationError):
        replace(monitor(), **changes)


def test_monitoring_covers_all_refusal_alert_and_rollback_fallbacks() -> None:
    rollback = evaluate_monitoring(replace(monitor(), mechanics_match=False))
    assert rollback.action == MonitorAction.ROLLBACK
    assert "no last compatible" in rollback.reasons[-1]

    refused = evaluate_monitoring(
        replace(monitor(), path_rejections=1, install_failures=1)
    )
    assert refused.action == MonitorAction.REFUSE
    assert len(refused.reasons) == 2

    alerted = evaluate_monitoring(replace(monitor(), invalid_state_rate=0.2))
    assert alerted.action == MonitorAction.ALERT
    no_exposures = replace(
        monitor(),
        exposures=0,
        adoptions=0,
        deviations=0,
        unhandled_branches=1,
    )
    assert evaluate_monitoring(no_exposures).action == MonitorAction.HEALTHY
