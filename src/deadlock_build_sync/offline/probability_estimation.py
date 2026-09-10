"""Fit the fixed probability model with median imputation and standard scaling."""

from __future__ import annotations

import numpy as np
from sklearn.preprocessing._data import _handle_zeros_in_scale, _is_constant_feature
from sklearn.utils.extmath import _incremental_mean_and_var
from sklearn.utils.validation import check_array

from .logistic_solver import fit_logistic_probabilities


def _impute_prediction_inputs(
    features: np.ndarray, prediction_features: np.ndarray, *, copy_training: bool
) -> tuple[np.ndarray, np.ndarray]:
    training = check_array(
        features,
        dtype=np.float64,
        copy=copy_training,
        ensure_all_finite="allow-nan",
        input_name="X",
    )
    testing = check_array(
        prediction_features,
        dtype=np.float64,
        copy=True,
        ensure_all_finite="allow-nan",
        input_name="X",
    )
    train_missing = np.isnan(training)
    test_missing = np.isnan(testing)
    columns = np.flatnonzero(train_missing.any(axis=0) | test_missing.any(axis=0))
    if len(columns):
        masked = np.ma.masked_array(
            training[:, columns], mask=train_missing[:, columns]
        )
        medians = np.ma.median(masked, axis=0).filled(0)
        for values, missing in ((training, train_missing), (testing, test_missing)):
            selected_rows, selected_columns = np.where(missing[:, columns])
            values[selected_rows, columns[selected_columns]] = medians[selected_columns]
    return training, testing


def fit_predict_probabilities(
    features: np.ndarray,
    labels: np.ndarray,
    prediction_features: np.ndarray,
    *,
    copy_training: bool = True,
) -> np.ndarray:
    if len(np.unique(labels)) < 2:
        return np.full(
            len(prediction_features), float((labels.sum() + 1) / (len(labels) + 2))
        )
    training, testing = _impute_prediction_inputs(
        features, prediction_features, copy_training=copy_training
    )
    _standardize_prediction_inputs(training, testing)
    return fit_logistic_probabilities(training, labels, testing)


def _standardize_prediction_inputs(training: np.ndarray, testing: np.ndarray) -> None:
    mean, variance, count = _incremental_mean_and_var(
        training, 0.0, 0.0, np.zeros(training.shape[1], dtype=np.int64)
    )
    scale = _handle_zeros_in_scale(
        np.sqrt(variance),
        copy=False,
        constant_mask=_is_constant_feature(variance, mean, count),
    )
    for values in (training, testing):
        np.subtract(values, mean, out=values)
        np.divide(values, scale, out=values)
