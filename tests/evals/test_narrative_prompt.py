from __future__ import annotations

import pytest
from deepeval.evaluate import assert_test

from evals.metrics import production_metrics
from evals.narrative_eval import (
    NarrativeCase,
    generate_test_case,
    load_cases,
)

CASES = load_cases()


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
def test_production_narrative_prompt(case: NarrativeCase) -> None:
    test_case = generate_test_case(case)
    assert_test(
        test_case,
        production_metrics(case.hero),
        run_async=False,
    )
