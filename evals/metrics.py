from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, override

from deepeval.metrics import BaseMetric

from scripts import generate_narratives

if TYPE_CHECKING:
    from deepeval.test_case import LLMTestCase


def _parse_object(output: str | None) -> tuple[dict[str, Any] | None, str | None]:
    try:
        parsed = json.loads(output or "")
    except json.JSONDecodeError as error:
        return None, str(error)
    if not isinstance(parsed, dict):
        return None, "response was not a JSON object"
    return parsed, None


def _ordered_action_identity(value: dict[str, Any]) -> tuple[tuple[str, str], ...]:
    rows = value.get("action_explanations")
    if not isinstance(rows, list):
        return ()
    return tuple(
        (str(row.get("node_id")), str(row.get("evidence_ref")))
        for row in rows
        if isinstance(row, dict)
    )


def _ordered_category_identity(value: dict[str, Any]) -> tuple[str, ...]:
    rows = value.get("category_summaries")
    if not isinstance(rows, list):
        return ()
    return tuple(str(row.get("category")) for row in rows if isinstance(row, dict))


class _SynchronousNarrativeMetric(BaseMetric):
    metric_name = "Narrative metric"

    def __init__(self, hero: dict[str, Any], *, threshold: float = 1.0) -> None:
        self.hero = hero
        self.threshold = threshold
        self.async_mode = False
        self.include_reason = True

    @property
    @override
    def __name__(self) -> str:
        """The report label configured by the subclass."""
        return self.metric_name

    @override
    async def a_measure(
        self,
        test_case: LLMTestCase,
        *_args: Any,
        **_kwargs: Any,
    ) -> float:
        """Run the deterministic synchronous metric in async evaluations.

        Returns:
            The deterministic metric score.

        """
        return self.measure(test_case)

    @override
    def is_successful(self) -> bool:
        """Report whether the latest measurement reached its threshold.

        Returns:
            Whether the most recent score passed.

        """
        return self.success is True

    def _record(self, score: float, reason: str) -> float:
        self.score = score
        self.success = score >= self.threshold
        self.reason = reason
        return score


class ProductionContractMetric(_SynchronousNarrativeMetric):
    """Apply the complete deterministic production validator."""

    metric_name = "Production contract"

    @override
    def measure(
        self,
        test_case: LLMTestCase,
        *_args: Any,
        **_kwargs: Any,
    ) -> float:
        """Validate one production response.

        Returns:
            One for an admitted response and zero otherwise.

        """
        response, error = _parse_object(test_case.actual_output)
        if response is None:
            return self._record(0.0, error or "invalid response")
        try:
            generate_narratives.validate_response(response, self.hero)
        except generate_narratives.GenerationError as validation_error:
            return self._record(0.0, str(validation_error))
        return self._record(1.0, "Production narrative validator passed")


class ClosedPolicyCoverageMetric(_SynchronousNarrativeMetric):
    """Check that every deterministic action and projection category is explained."""

    metric_name = "Closed policy coverage"

    @override
    def measure(
        self,
        test_case: LLMTestCase,
        *_args: Any,
        **_kwargs: Any,
    ) -> float:
        """Measure exact ordered action and category coverage.

        Returns:
            One only when the deterministic identities are unchanged.

        """
        response, error = _parse_object(test_case.actual_output)
        if response is None:
            return self._record(0.0, error or "invalid response")
        supplied_actions = self.hero.get("explainable_actions")
        expected_actions = tuple(
            (str(row.get("node_id")), str(row.get("evidence_ref")))
            for row in supplied_actions or []
            if isinstance(row, dict)
        )
        projection = self.hero.get("projection")
        categories = (
            projection.get("categories") if isinstance(projection, dict) else []
        )
        expected_categories = tuple(
            str(row.get("name")) for row in categories or [] if isinstance(row, dict)
        )
        if _ordered_action_identity(response) != expected_actions:
            return self._record(0.0, "Action identity or order changed")
        if _ordered_category_identity(response) != expected_categories:
            return self._record(0.0, "Projection category identity or order changed")
        return self._record(1.0, "All closed-policy actions and categories are covered")


class EvidenceLanguageMetric(_SynchronousNarrativeMetric):
    """Reject causal, unit-leaking, or non-actionable policy explanations."""

    metric_name = "Evidence language ceiling"

    @override
    def measure(
        self,
        test_case: LLMTestCase,
        *_args: Any,
        **_kwargs: Any,
    ) -> float:
        """Measure the production evidence-language ceiling.

        Returns:
            One when deterministic language validation succeeds.

        """
        response, error = _parse_object(test_case.actual_output)
        if response is None:
            return self._record(0.0, error or "invalid response")
        try:
            generate_narratives.validate_response(response, self.hero)
        except generate_narratives.GenerationError as validation_error:
            return self._record(0.0, str(validation_error))
        return self._record(
            1.0,
            "All prose stays within supplied claim classes and observable triggers",
        )


class RepeatedGenerationStabilityMetric(_SynchronousNarrativeMetric):
    """Score completion and structural stability across repeated generations."""

    metric_name = "Repeated-generation stability"

    def __init__(self, hero: dict[str, Any]) -> None:
        super().__init__(hero, threshold=0.9)

    @override
    def measure(
        self,
        test_case: LLMTestCase,
        *_args: Any,
        **_kwargs: Any,
    ) -> float:
        """Measure repeated completion, contract, and identity stability.

        Returns:
            The minimum score across the separately reported dimensions.

        """
        try:
            samples = json.loads(test_case.actual_output or "")
        except json.JSONDecodeError as error:
            return self._record(0.0, str(error))
        if not isinstance(samples, list) or len(samples) < 2:
            return self._record(0.0, "Reliability output did not contain repeats")
        outputs = [
            sample["output"]
            for sample in samples
            if isinstance(sample, dict) and isinstance(sample.get("output"), dict)
        ]
        completion = len(outputs) / len(samples)
        valid_outputs: list[dict[str, Any]] = []
        for output in outputs:
            try:
                generate_narratives.validate_response(output, self.hero)
            except generate_narratives.GenerationError:
                continue
            valid_outputs.append(output)
        contract = len(valid_outputs) / len(samples)
        action_identities = {
            _ordered_action_identity(output) for output in valid_outputs
        }
        category_identities = {
            _ordered_category_identity(output) for output in valid_outputs
        }
        ending_identities = {
            tuple(
                output
                .get("tactical_profile", {})
                .get("ending_duration_interpretation", {})
                .get(field)
                for field in ("estimand", "strongest_phase", "weakest_phase")
            )
            for output in valid_outputs
        }
        enough = len(valid_outputs) >= 2
        breakdown = {
            "completion": completion,
            "production_contract": contract,
            "action_identity": float(enough and len(action_identities) == 1),
            "category_identity": float(enough and len(category_identities) == 1),
            "ending_estimand_identity": float(enough and len(ending_identities) == 1),
        }
        self.score_breakdown = breakdown
        score = min(breakdown.values())
        weak = [f"{name}={value:.2f}" for name, value in breakdown.items() if value < 1]
        errors = [
            str(sample.get("error"))
            for sample in samples
            if isinstance(sample, dict) and sample.get("error")
        ]
        if weak:
            reason = "Reliability shortfalls: " + ", ".join(weak)
            if errors:
                reason += "; errors: " + " | ".join(errors)
        else:
            reason = (
                f"{len(valid_outputs)}/{len(samples)} stable closed-policy explanations"
            )
        return self._record(score, reason)


def production_metrics(hero: dict[str, Any]) -> list[BaseMetric]:
    """Build separate contract, policy-coverage, and language metrics.

    Returns:
        The production DeepEval metrics for one hero packet.

    """
    return [
        ProductionContractMetric(hero),
        ClosedPolicyCoverageMetric(hero),
        EvidenceLanguageMetric(hero),
    ]
