from __future__ import annotations

from unittest.mock import Mock

import numpy as np
import polars as pl
import pytest
from threadpoolctl import threadpool_limits

from deadlock_build_sync.offline import contrast_screening as screening
from deadlock_build_sync.offline import doubly_robust_estimation as estimation
from deadlock_build_sync.offline.contrast_observations import ContrastObservations
from deadlock_build_sync.offline.discovery_branches import BranchCandidateEvaluator
from tests.offline.production_evidence_fixtures import make_contrast_rows
from tests.offline.test_discovery_branches import decisions, nominee
from tests.purchase_guidance_fixtures import make_purchase_guidance


def test_screening_preserves_complete_passing_contrasts_without_extra_fits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame = pl.DataFrame(make_contrast_rows(positive=True))
    measured = Mock(wraps=estimation.fit_predict_probabilities)

    with threadpool_limits(limits=1):
        expected = estimation.estimate_cross_fitted_doubly_robust_contrast(
            frame, 10, 20
        )
        monkeypatch.setattr(estimation, "fit_predict_probabilities", measured)
        monkeypatch.setattr(screening, "fit_predict_probabilities", measured)
        actual = estimation.estimate_admissible_contrast(frame, 10, 20)
    assert actual == expected
    assert isinstance(actual, estimation.DoublyRobustContrast)
    assert actual.admitted
    assert measured.call_count == 45


@pytest.mark.parametrize(
    ("period", "outcome_calls"), [("train", 0), ("validation", 10)]
)
def test_failed_balance_stops_later_outcome_models(
    monkeypatch: pytest.MonkeyPatch, period: str, outcome_calls: int
) -> None:
    frame = pl.DataFrame(make_contrast_rows(positive=True)).with_columns(
        ((pl.col("fold") == period) & (pl.col("item_id") == 10))
        .cast(pl.Int8)
        .alias("context_separated")
    )
    measured = Mock(wraps=estimation.fit_predict_probabilities)

    with threadpool_limits(limits=1):
        expected = estimation.estimate_cross_fitted_doubly_robust_contrast(
            frame, 10, 20
        )
        monkeypatch.setattr(estimation, "fit_predict_probabilities", measured)
        rejection = estimation.estimate_admissible_contrast(frame, 10, 20)
    assert isinstance(rejection, screening.ContrastBalanceRejection)
    assert rejection.fold == period
    assert (
        rejection.maximum_standardized_mean_difference
        == expected.fold_diagnostics[period]["maximum_standardized_mean_difference"]
    )
    assert not expected.admitted
    assert measured.call_count == outcome_calls


def test_screening_handles_empty_cross_fit_groups() -> None:
    observations = ContrastObservations(
        np.zeros((4, 1)),
        np.array([0, 1, 0, 1]),
        np.array([0, 1, 1, 0]),
        np.array([1, 1, 2, 2]),
    )
    with threadpool_limits(limits=1):
        propensity = screening.require_contrast_balance(observations, "train", 5)
    np.testing.assert_array_equal(propensity, np.full(4, 0.5))


def test_rejected_comparisons_keep_the_failed_check_and_reuse_results() -> None:
    _, graph = make_purchase_guidance()
    rows = [
        {**row, "context_separated": int(row["item_id"] == 7)} for row in decisions()
    ]
    candidate: dict[str, object] = {
        "item_id": 7,
        "comparator_item_id": 2,
        "after_step": 2,
        "condition": "relative_wealth",
        "value": "behind",
    }
    evaluator = BranchCandidateEvaluator(rows, graph, 1)
    with threadpool_limits(limits=1):
        first = evaluator.evaluate_candidates(nominee(), [candidate])
        repeated = evaluator.evaluate_candidates(nominee(), [candidate])
    assert first == repeated
    assert not first["branches"]
    assert first["audit"] == [
        {
            **candidate,
            "admitted": False,
            "reason": "Balance check failed; later outcome diagnostics were not calculated",
            "balance_screening": {
                "fold": "train",
                "support": 400,
                "comparison_support": 400,
                "maximum_standardized_mean_difference": None,
            },
        }
    ]
    assert evaluator.contrast_cache.calculated_fits == 1
    assert evaluator.contrast_cache.reused_fits == 1
    assert evaluator.contrast_cache.rejected_at_balance == 1
