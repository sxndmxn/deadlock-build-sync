from __future__ import annotations

import numpy as np
import pytest
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

from deadlock_build_sync.offline.probability_estimation import (
    _standardize_prediction_inputs,
    fit_predict_probabilities,
)


@pytest.mark.parametrize("missing", [False, True])
@pytest.mark.parametrize("copy_training", [False, True])
def test_probability_predictions_match_the_fixed_pipeline(
    *, missing: bool, copy_training: bool
) -> None:
    generator = np.random.default_rng(719)
    training = generator.normal(size=(93, 17))
    testing = generator.normal(size=(29, 17))
    labels = generator.integers(0, 2, len(training))
    training[:, 0] = 1
    testing[:, 0] = 1
    if missing:
        training[::3, 2] = np.nan
        training[:, 5] = np.nan
        testing[::2, 5] = np.nan
        testing[::3, 8] = np.nan
    original_training, original_testing = training.copy(), testing.copy()
    reference = make_pipeline(
        SimpleImputer(strategy="median", keep_empty_features=True),
        StandardScaler(),
        LogisticRegression(C=0.5, max_iter=500, solver="lbfgs"),
    )
    with threadpool_limits(limits=1):
        expected = reference.fit(training, labels).predict_proba(testing)[:, 1]
        actual = fit_predict_probabilities(
            training if copy_training else training.copy(),
            labels,
            testing,
            copy_training=copy_training,
        )
    np.testing.assert_array_equal(actual, expected)
    np.testing.assert_array_equal(training, original_training)
    np.testing.assert_array_equal(testing, original_testing)


@pytest.mark.parametrize("label", [0, 1])
def test_constant_outcomes_keep_smoothed_probabilities(label: int) -> None:
    labels = np.full(7, label)
    predictions = fit_predict_probabilities(np.ones((7, 3)), labels, np.ones((4, 3)))
    np.testing.assert_array_equal(predictions, np.full(4, (labels.sum() + 1) / 9))


@pytest.mark.parametrize("prediction", [False, True])
def test_probability_inputs_reject_infinite_values(*, prediction: bool) -> None:
    training, testing = np.ones((8, 3)), np.ones((4, 3))
    (testing if prediction else training)[0, 0] = np.inf
    with pytest.raises(ValueError, match="infinity"):
        fit_predict_probabilities(training, np.arange(8) % 2, testing)


@pytest.mark.parametrize("offset", [0.0, 1e15])
def test_standardization_matches_constant_and_near_constant_features(
    offset: float,
) -> None:
    generator = np.random.default_rng(317)
    training = generator.normal(size=(81, 9)) + offset
    testing = generator.normal(size=(13, 9)) + offset
    training[:, 0] = 0
    training[:, 1] = 1e15
    training[0, 1] += 0.125
    scaler = StandardScaler()
    expected_training = scaler.fit_transform(training)
    expected_testing = scaler.transform(testing)
    _standardize_prediction_inputs(training, testing)
    np.testing.assert_array_equal(training, expected_training)
    np.testing.assert_array_equal(testing, expected_testing)
