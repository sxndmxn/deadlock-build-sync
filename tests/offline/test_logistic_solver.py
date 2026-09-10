from __future__ import annotations

import numpy as np
import pytest
from sklearn.linear_model import LogisticRegression
from threadpoolctl import threadpool_limits

from deadlock_build_sync.offline import logistic_solver


@pytest.mark.parametrize("classes", [2, 3])
def test_solver_probabilities_match_the_original_estimator(classes: int) -> None:
    generator = np.random.default_rng(517)
    training = generator.normal(size=(101, 13))
    testing = generator.normal(size=(37, 13))
    labels = np.arange(len(training)) % classes
    with threadpool_limits(limits=1):
        model = LogisticRegression(C=0.5, max_iter=500, solver="lbfgs").fit(
            training, labels
        )
        actual = logistic_solver.fit_logistic_probabilities(training, labels, testing)
    np.testing.assert_array_equal(actual, model.predict_proba(testing)[:, 1])


@pytest.mark.parametrize("task", [1, 8])
def test_unsuccessful_solver_returns_to_the_original_estimator(
    monkeypatch: pytest.MonkeyPatch, task: int
) -> None:
    def advance(
        workspace: logistic_solver._SolverWorkspace,
        _value: float | np.ndarray,
        _gradient: np.ndarray,
    ) -> None:
        workspace.task[0] = task

    monkeypatch.setattr(logistic_solver._SolverWorkspace, "advance", advance)
    training = np.arange(32, dtype=float).reshape(16, 2)
    labels = np.arange(16) % 2
    expected = LogisticRegression(C=0.5, max_iter=500, solver="lbfgs").fit(
        training, labels
    )
    actual = logistic_solver.fit_logistic_probabilities(training, labels, training)
    np.testing.assert_array_equal(actual, expected.predict_proba(training)[:, 1])


@pytest.mark.parametrize("labels", [np.array([0, 1]), np.array([0.2, 0.8, 0.2, 0.8])])
def test_invalid_labels_retain_the_original_input_checks(labels: np.ndarray) -> None:
    with pytest.raises(ValueError, match=r"inconsistent|Unknown label type"):
        logistic_solver.fit_logistic_probabilities(
            np.ones((4, 2)), labels, np.ones((2, 2))
        )
