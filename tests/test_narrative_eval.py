from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest
from deepeval.test_case import LLMTestCase

from evals import metrics, narrative_eval
from scripts import generate_narratives

if TYPE_CHECKING:
    from pathlib import Path


def test_load_cases_selects_requested_heroes(tmp_path: Path) -> None:
    context_path = tmp_path / "context.json"
    context_path.write_text(
        json.dumps({
            "item_mechanics": {"101": {"cost": 500}},
            "heroes": [
                {"hero_id": 12, "hero": "Kelvin"},
                {"hero_id": 19, "hero": "Shiv"},
            ],
        }),
        encoding="utf-8",
    )

    cases = narrative_eval.load_cases(context_path, ["Shiv", "Kelvin"])

    assert [case.name for case in cases] == ["Shiv", "Kelvin"]
    assert cases[0].hero["hero_id"] == 19
    assert cases[0].item_mechanics["101"] == {"cost": 500}


def test_load_cases_reports_missing_heroes(tmp_path: Path) -> None:
    context_path = tmp_path / "context.json"
    context_path.write_text(
        json.dumps({"item_mechanics": {}, "heroes": []}),
        encoding="utf-8",
    )

    with pytest.raises(narrative_eval.NarrativeEvalError, match="missing hero"):
        narrative_eval.load_cases(context_path, ["Kelvin"])


def test_generate_test_case_calls_both_production_stages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hero = {
        "hero_id": 12,
        "path_id": "default",
        "hero": "Kelvin",
        "kit_basis_sha256": "d" * 64,
    }
    case = narrative_eval.NarrativeCase(hero=hero, regression="baseline")
    calls: list[tuple[dict[str, Any], generate_narratives.GenerationStage]] = []

    def generate_validated_response(
        model_input: dict[str, Any],
        _validation_context: dict[str, Any],
        stage: generate_narratives.GenerationStage,
    ) -> dict[str, Any]:
        calls.append((model_input, stage))
        if stage.schema_path == narrative_eval.KIT_SCHEMA_PATH:
            return {"hero_id": 12, "kit_basis_sha256": "d" * 64}
        return {"hero_id": 12, "validated": True}

    monkeypatch.setattr(
        generate_narratives,
        "generate_validated_response",
        generate_validated_response,
    )

    test_case = narrative_eval.generate_test_case(
        case,
        model="synthesis-model",
        kit_model="kit-model",
    )

    assert json.loads(test_case.actual_output or "") == {
        "hero_id": 12,
        "validated": True,
    }
    assert [stage.schema_path for _, stage in calls] == [
        narrative_eval.KIT_SCHEMA_PATH,
        narrative_eval.SCHEMA_PATH,
    ]
    assert [stage.model for _, stage in calls] == ["kit-model", "synthesis-model"]
    assert calls[1][1].identity_fields == (
        "hero_id",
        "path_id",
        "snapshot_id",
        "policy_id",
        "context_sha256",
        "narrative_basis_sha256",
    )
    assert all(
        stage.max_attempts == generate_narratives.DEFAULT_GENERATION_ATTEMPTS
        for _, stage in calls
    )
    assert all(
        stage.timeout_seconds == narrative_eval.EVAL_TIMEOUT_SECONDS
        for _, stage in calls
    )
    assert calls[1][0]["preliminary_kit_analysis"] == {
        "hero_id": 12,
        "kit_basis_sha256": "d" * 64,
    }
    assert test_case.metadata == {
        "hero": "Kelvin",
        "hero_id": 12,
        "regression": "baseline",
        "kit_model": "kit-model",
        "synthesis_model": "synthesis-model",
        "kit_profile": {"hero_id": 12, "kit_basis_sha256": "d" * 64},
    }


def test_production_contract_metric_uses_production_validator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hero = {"hero_id": 12, "hero": "Kelvin"}
    response = {"hero_id": 12}

    def validate_response(
        received_response: dict[str, Any],
        received_hero: dict[str, Any],
        *,
        require_context_match: bool = True,
    ) -> dict[str, Any]:
        assert received_response == response
        assert received_hero is hero
        assert require_context_match
        return received_response

    monkeypatch.setattr(
        generate_narratives,
        "validate_response",
        validate_response,
    )
    metric = metrics.ProductionContractMetric(hero)

    score = metric.measure(
        LLMTestCase(input="prompt", actual_output=json.dumps(response))
    )

    assert score == 1.0
    assert metric.is_successful()
    assert metric.reason == "Production narrative validator passed"


def test_production_contract_metric_reports_validation_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hero = {"hero_id": 12, "hero": "Kelvin"}

    def reject_response(*_args: object, **_kwargs: object) -> dict[str, Any]:
        raise generate_narratives.GenerationError("missing active instruction")

    monkeypatch.setattr(
        generate_narratives,
        "validate_response",
        reject_response,
    )
    metric = metrics.ProductionContractMetric(hero)

    score = metric.measure(LLMTestCase(input="prompt", actual_output="{}"))

    assert score == 0.0
    assert not metric.is_successful()
    assert metric.reason == "missing active instruction"


def test_generate_reliability_case_retains_generation_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hero = {
        "hero_id": 12,
        "hero": "Kelvin",
        "kit_basis_sha256": "d" * 64,
    }
    case = narrative_eval.NarrativeCase(hero=hero, regression="baseline")
    synthesis_attempt = 0

    def generate_validated_response(
        _model_input: dict[str, Any],
        _validation_context: dict[str, Any],
        stage: generate_narratives.GenerationStage,
    ) -> dict[str, Any]:
        nonlocal synthesis_attempt
        assert stage.timeout_seconds == 5
        assert stage.max_attempts == generate_narratives.DEFAULT_GENERATION_ATTEMPTS
        if stage.schema_path == narrative_eval.KIT_SCHEMA_PATH:
            return {"hero_id": 12, "kit_basis_sha256": "d" * 64}
        synthesis_attempt += 1
        if synthesis_attempt == 2:
            raise generate_narratives.GenerationError("timed out")
        return {"hero_id": 12, "attempt": synthesis_attempt}

    monkeypatch.setattr(
        generate_narratives,
        "generate_validated_response",
        generate_validated_response,
    )

    test_case = narrative_eval.generate_reliability_test_case(
        case,
        repeats=3,
        timeout_seconds=5,
    )
    samples = json.loads(test_case.actual_output or "")

    assert [sample.get("attempt") for sample in samples] == [1, 2, 3]
    assert samples[0]["output"]["attempt"] == 1
    assert samples[1]["error"] == "timed out"
    assert samples[2]["output"]["attempt"] == 3


def test_reliability_case_requires_multiple_generations() -> None:
    case = narrative_eval.NarrativeCase(hero={"hero": "Kelvin"}, regression="")

    with pytest.raises(narrative_eval.NarrativeEvalError, match="at least 2"):
        narrative_eval.generate_reliability_test_case(case, repeats=1)
