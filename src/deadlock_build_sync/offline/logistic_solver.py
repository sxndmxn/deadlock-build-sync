"""Use the fixed binary L-BFGS-B solver with the original loss and tolerances."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.optimize._lbfgsb_py import _lbfgsb
from scipy.special import expit
from sklearn._loss.loss import HalfBinomialLoss
from sklearn.linear_model import LogisticRegression
from sklearn.linear_model._linear_loss import LinearModelLoss


@dataclass
class _SolverWorkspace:
    size: int
    coefficients: np.ndarray = field(init=False)
    lower: np.ndarray = field(init=False)
    upper: np.ndarray = field(init=False)
    bounds: np.ndarray = field(init=False)
    values: np.ndarray = field(init=False)
    indices: np.ndarray = field(init=False)
    task: np.ndarray = field(default_factory=lambda: np.zeros(2, dtype=np.int32))
    line_task: np.ndarray = field(default_factory=lambda: np.zeros(2, dtype=np.int32))
    logical: np.ndarray = field(default_factory=lambda: np.zeros(4, dtype=np.int32))
    integers: np.ndarray = field(default_factory=lambda: np.zeros(44, dtype=np.int32))
    doubles: np.ndarray = field(default_factory=lambda: np.zeros(29))

    def __post_init__(self) -> None:
        self.coefficients = np.zeros(self.size)
        self.lower = np.zeros(self.size)
        self.upper = np.zeros(self.size)
        self.bounds = np.zeros(self.size, dtype=np.int32)
        self.values = np.zeros(25 * self.size + 1180)
        self.indices = np.zeros(3 * self.size, dtype=np.int32)

    def advance(self, value: float | np.ndarray, gradient: np.ndarray) -> None:
        _lbfgsb.setulb(
            10,
            self.coefficients,
            self.lower,
            self.upper,
            self.bounds,
            value,
            gradient.astype(np.float64),
            64.0,
            1e-4,
            self.values,
            self.indices,
            self.task,
            self.logical,
            self.integers,
            self.doubles,
            50,
            self.line_task,
        )


def _solve_binary_coefficients(
    features: np.ndarray, labels: np.ndarray
) -> np.ndarray | None:
    workspace = _SolverWorkspace(features.shape[1] + 1)
    objective = LinearModelLoss(base_loss=HalfBinomialLoss(), fit_intercept=True)
    target = labels.astype(np.float64)
    value, gradient = np.array(0.0), np.zeros(workspace.size)
    iterations, evaluations = 0, 0
    while True:
        workspace.advance(value, gradient)
        if workspace.task[0] == 3:
            value, gradient = objective.loss_gradient(
                workspace.coefficients,
                features,
                target,
                None,
                1.0 / (0.5 * len(labels)),
                1,
            )
            evaluations += 1
        elif workspace.task[0] == 1:
            iterations += 1
            if iterations >= 500 or evaluations > 15000:
                return None
        else:
            return workspace.coefficients if workspace.task[0] == 4 else None


def fit_logistic_probabilities(
    features: np.ndarray, labels: np.ndarray, prediction_features: np.ndarray
) -> np.ndarray:
    coefficients = (
        _solve_binary_coefficients(features, labels)
        if labels.ndim == 1
        and len(labels) == len(features)
        and np.array_equal(np.unique(labels), [0, 1])
        and np.isfinite(features).all()
        and np.isfinite(prediction_features).all()
        else None
    )
    if coefficients is None:
        # The original estimator retains its convergence warnings and failure behavior.
        model = LogisticRegression(C=0.5, max_iter=500, solver="lbfgs")
        model.fit(features, labels)
        return model.predict_proba(prediction_features)[:, 1]
    scores = (
        prediction_features @ coefficients[:-1].reshape(-1, 1) + coefficients[-1:]
    ).ravel()
    return expit(scores, out=scores)
