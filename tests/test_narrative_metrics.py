import json
from typing import Any

import pytest
from deepeval.test_case import LLMTestCase

from evals import metrics
from scripts import generate_narratives


def hero() -> dict[str, Any]:
    return {
        "hero_id": 12,
        "explainable_actions": [
            {"node_id": "core", "evidence_ref": "item/101"},
            {"node_id": "counter", "evidence_ref": "item/102"},
        ],
        "projection": {
            "categories": [
                {"name": "CORE — DEFAULT QUEUE"},
                {"name": "IF BURST"},
            ]
        },
    }


def response() -> dict[str, Any]:
    return {
        "build_summary": "Follow the default and adapt through optional menus.",
        "action_explanations": [
            {
                "node_id": "core",
                "evidence_ref": "item/101",
                "instruction": "Use the default.",
            },
            {
                "node_id": "counter",
                "evidence_ref": "item/102",
                "instruction": "Use the counter when observed.",
            },
        ],
        "category_summaries": [
            {"category": "CORE — DEFAULT QUEUE", "summary": "Default."},
            {"category": "IF BURST", "summary": "Conditional."},
        ],
        "tactical_profile": {
            "primary_role": "Mobile pressure",
            "fight_role": "Maintain contact and convert clean picks.",
            "economy_plan": "Build the core in order unless the state changes.",
            "ending_duration_interpretation": {
                "estimand": "ending_duration_profile",
                "strongest_phase": "LATE (45m+)",
                "weakest_phase": "EARLY (<30m)",
                "plan": "Convert clean opportunities.",
            },
        },
    }


def case(output: object) -> LLMTestCase:
    return LLMTestCase(input="prompt", actual_output=json.dumps(output))


def test_closed_policy_metric_requires_exact_action_and_category_order() -> None:
    metric = metrics.ClosedPolicyCoverageMetric(hero())

    assert metric.measure(case(response())) == 1.0

    invalid = response()
    invalid["action_explanations"].reverse()
    assert metric.measure(case(invalid)) == 0.0
    assert metric.reason == "Action identity or order changed"


def test_evidence_language_metric_uses_production_validator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[dict[str, Any]] = []

    def validate(value: dict[str, Any], _hero: dict[str, Any]) -> dict[str, Any]:
        seen.append(value)
        return value

    monkeypatch.setattr(generate_narratives, "validate_response", validate)
    metric = metrics.EvidenceLanguageMetric(hero())

    assert metric.measure(case(response())) == 1.0
    assert seen == [response()]


def test_evidence_language_metric_reports_claim_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reject(*_args: object, **_kwargs: object) -> dict[str, Any]:
        raise generate_narratives.GenerationError("causal language")

    monkeypatch.setattr(generate_narratives, "validate_response", reject)
    metric = metrics.EvidenceLanguageMetric(hero())

    assert metric.measure(case(response())) == 0.0
    assert metric.reason == "causal language"


def test_projection_utilization_requires_every_generated_field_family() -> None:
    metric = metrics.ProjectionUtilizationMetric(hero())

    assert metric.measure(case(response())) == 1.0

    incomplete = response()
    incomplete.pop("build_summary")
    assert metric.measure(case(incomplete)) == 0.0
    assert isinstance(metric.reason, str)
    assert "build_summary" in metric.reason


def test_repeated_metric_passes_structurally_stable_outputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        generate_narratives,
        "validate_response",
        lambda value, _hero: value,
    )
    varied = response()
    varied["tactical_profile"]["ending_duration_interpretation"]["plan"] = (
        "Use a different but still conservative plan."
    )
    samples = [
        {"attempt": 1, "output": response(), "duration_seconds": 1.0},
        {"attempt": 2, "output": varied, "duration_seconds": 1.0},
        {"attempt": 3, "output": response(), "duration_seconds": 1.0},
    ]
    metric = metrics.RepeatedGenerationStabilityMetric(hero())

    assert metric.measure(case(samples)) == 1.0
    assert metric.score_breakdown == {
        "completion": 1.0,
        "production_contract": 1.0,
        "action_identity": 1.0,
        "category_identity": 1.0,
        "ending_estimand_identity": 1.0,
    }


def test_repeated_metric_counts_generation_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        generate_narratives,
        "validate_response",
        lambda value, _hero: value,
    )
    samples = [
        {"attempt": 1, "output": response()},
        {"attempt": 2, "error": "timeout"},
        {"attempt": 3, "output": response()},
    ]
    metric = metrics.RepeatedGenerationStabilityMetric(hero())

    assert metric.measure(case(samples)) == pytest.approx(2 / 3)
    assert isinstance(metric.reason, str)
    assert "timeout" in metric.reason
