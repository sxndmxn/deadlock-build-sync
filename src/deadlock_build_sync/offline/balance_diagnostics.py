"""Calculate weighted standardized differences with the original reduction order."""

from __future__ import annotations

import math

import numpy as np


def _calculate_incomplete_feature_difference(
    features: np.ndarray, treatment: np.ndarray, weights: np.ndarray
) -> float:
    maximum = 0.0
    for column in range(features.shape[1]):
        values = features[:, column]
        valid = np.isfinite(values)
        treated = valid & (treatment == 1)
        control = valid & (treatment == 0)
        if not treated.any() or not control.any():
            continue
        treated_mean = np.average(values[treated], weights=weights[treated])
        control_mean = np.average(values[control], weights=weights[control])
        pooled = math.sqrt(
            (
                np.average(
                    (values[treated] - treated_mean) ** 2, weights=weights[treated]
                )
                + np.average(
                    (values[control] - control_mean) ** 2, weights=weights[control]
                )
            )
            / 2
        )
        if pooled > 0:
            maximum = max(maximum, abs(treated_mean - control_mean) / pooled)
        elif treated_mean != control_mean:
            return float("inf")
    return maximum


def _calculate_group_statistics(
    values: np.ndarray, selected: np.ndarray, weights: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    group = np.ascontiguousarray(values[:, selected])
    group_weights = weights[selected]
    means = np.sum(group * group_weights, axis=1) / group_weights.sum()
    variances = (
        np.sum((group - means[:, None]) ** 2 * group_weights, axis=1)
        / group_weights.sum()
    )
    return means, variances


def calculate_maximum_weighted_standardized_difference(
    features: np.ndarray, treatment: np.ndarray, propensity: np.ndarray
) -> float:
    complete = np.isfinite(features).all(axis=0)
    weights = np.where(treatment == 1, 1 / propensity, 1 / (1 - propensity))
    maximum = _calculate_incomplete_feature_difference(
        features[:, ~complete], treatment, weights
    )
    if not complete.any() or not np.any(treatment == 1) or not np.any(treatment == 0):
        return maximum
    values = features[:, complete].T
    treated_mean, treated_variance = _calculate_group_statistics(
        values, treatment == 1, weights
    )
    control_mean, control_variance = _calculate_group_statistics(
        values, treatment == 0, weights
    )
    pooled = np.sqrt((treated_variance + control_variance) / 2)
    difference = abs(treated_mean - control_mean)
    if np.any(~(pooled > 0) & (difference != 0)):
        return float("inf")
    ratios = np.divide(
        difference, pooled, out=np.zeros_like(difference), where=pooled > 0
    )
    return max(maximum, float(np.where(np.isnan(ratios), 0, ratios).max(initial=0)))
