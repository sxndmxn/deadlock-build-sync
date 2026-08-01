from __future__ import annotations

import pytest
from deepeval.evaluate import assert_test

from evals.metrics import RepeatedGenerationStabilityMetric
from evals.narrative_eval import (
    NarrativeCase,
    generate_reliability_test_case,
    load_cases,
)

CASES = load_cases()


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
def test_repeated_narrative_generation(case: NarrativeCase) -> None:
    test_case = generate_reliability_test_case(case)
    assert_test(
        test_case,
        [RepeatedGenerationStabilityMetric(case.hero)],
        run_async=False,
    )
