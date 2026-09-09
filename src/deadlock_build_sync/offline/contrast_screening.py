"""Reject failed balance before calculating outcome evidence."""

from dataclasses import dataclass

import numpy as np

from .balance_diagnostics import calculate_maximum_weighted_standardized_difference
from .contrast_observations import ContrastObservations
from .effect_estimation_limits import (
    MAXIMUM_STANDARDIZED_MEAN_DIFFERENCE,
    PROPENSITY_FLOOR,
)
from .probability_estimation import fit_predict_probabilities


@dataclass(frozen=True)
class ContrastBalanceRejection:
    fold: str
    support: int
    comparison_support: int
    maximum_standardized_mean_difference: float


class ContrastBalanceError(ValueError):
    def __init__(self, rejection: ContrastBalanceRejection) -> None:
        self.rejection = rejection
        super().__init__(f"Balance check failed in {rejection.fold}")


def require_contrast_balance(
    observations: ContrastObservations, period: str, folds: int
) -> np.ndarray:
    groups = observations.match_folds(folds)
    propensity = np.zeros(len(observations.treatment))
    for fold in range(folds):
        test = groups == fold
        if not test.any():
            continue
        propensity[test] = fit_predict_probabilities(
            observations.features[~test],
            observations.treatment[~test],
            observations.features[test],
            copy_training=False,
        )
    propensity = np.clip(propensity, PROPENSITY_FLOOR, 1 - PROPENSITY_FLOOR)
    difference = calculate_maximum_weighted_standardized_difference(
        observations.features, observations.treatment, propensity
    )
    if difference > MAXIMUM_STANDARDIZED_MEAN_DIFFERENCE:
        support = int(observations.treatment.sum())
        raise ContrastBalanceError(
            ContrastBalanceRejection(
                period, support, len(propensity) - support, difference
            )
        )
    return propensity
