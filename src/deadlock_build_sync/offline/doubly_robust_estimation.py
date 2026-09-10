from __future__ import annotations

import math
from dataclasses import dataclass
from typing import cast

import numpy as np
import polars as pl

from deadlock_build_sync.value_validation import integer, number

from .balance_diagnostics import (
    calculate_maximum_weighted_standardized_difference as _calculate_maximum_weighted_standardized_difference,
)
from .contrast_features import build_contrast_feature_matrix
from .contrast_observations import ContrastObservations
from .contrast_screening import (
    ContrastBalanceError,
    ContrastBalanceRejection,
    require_contrast_balance,
)
from .effect_estimation_limits import (
    MAXIMUM_INTERVAL_WIDTH,
    MAXIMUM_STANDARDIZED_MEAN_DIFFERENCE,
    MINIMUM_EFFECTIVE_SUPPORT,
    MINIMUM_OVERLAP,
    MINIMUM_SUPPORT,
    PROPENSITY_FLOOR,
    SELECTION_FOLDS,
    WEIGHT_CLIP_LIMITS,
)
from .probability_estimation import fit_predict_probabilities


@dataclass(frozen=True)
class DoublyRobustContrast:
    treatment_item_id: int
    comparator_item_id: int
    support: int
    comparison_support: int
    effective_support: float
    overlap: float
    maximum_weight: float
    maximum_standardized_mean_difference: float
    estimate: float
    interval: tuple[float, float]
    fold_estimates: dict[str, float]
    fold_diagnostics: dict[str, dict[str, object]]
    clipped_sensitivity: dict[str, float]
    stable: bool
    admitted: bool
    failed_gates: tuple[str, ...]


def _calculate_cross_fitted_scores(
    observations: ContrastObservations,
    folds: int,
    propensity: np.ndarray | None = None,
) -> dict[str, np.ndarray]:
    features, treatment = observations.features, observations.treatment
    outcome, match_ids = observations.outcome, observations.match_ids
    fit_propensity = propensity is None
    if propensity is None:
        propensity = np.zeros(len(treatment))
    outcome_treated = np.zeros(len(treatment))
    outcome_control = np.zeros(len(treatment))
    cross_fit_fold = observations.match_folds(folds)
    for fold in range(folds):
        test = cross_fit_fold == fold
        train = ~test
        if not test.any():
            continue
        prediction_features = features[test]
        if fit_propensity:
            propensity[test] = fit_predict_probabilities(
                features[train],
                treatment[train],
                prediction_features,
                copy_training=False,
            )
        for action, destination in (
            (1, outcome_treated),
            (0, outcome_control),
        ):
            action_train = train & (treatment == action)
            if not action_train.any():
                destination[test] = outcome[train].mean()
                continue
            destination[test] = fit_predict_probabilities(
                features[action_train],
                outcome[action_train],
                prediction_features,
                copy_training=False,
            )
    propensity = np.clip(propensity, PROPENSITY_FLOOR, 1 - PROPENSITY_FLOOR)
    score_treated = outcome_treated + treatment / propensity * (
        outcome - outcome_treated
    )
    score_control = outcome_control + (1 - treatment) / (1 - propensity) * (
        outcome - outcome_control
    )
    return {
        "features": features,
        "treatment": treatment,
        "outcome": outcome,
        "propensity": propensity,
        "influence": score_treated - score_control,
        "match_ids": match_ids,
        "outcome_treated": outcome_treated,
        "outcome_control": outcome_control,
    }


def _calculate_cluster_interval(
    influence: np.ndarray, match_ids: np.ndarray
) -> tuple[float, float]:
    estimate = float(influence.mean())
    matches, counts = np.unique(match_ids, return_counts=True)
    if len(matches) < 2:
        return estimate, estimate
    ordered = influence[np.argsort(match_ids, kind="stable")]
    clusters = (
        ordered
        if len(matches) == len(match_ids)
        else np.array([
            part.mean() for part in np.split(ordered, np.cumsum(counts)[:-1])
        ])
    )
    standard_error = float(np.std(clusters, ddof=1) / math.sqrt(len(clusters)))
    return estimate - 1.96 * standard_error, estimate + 1.96 * standard_error


def _evaluate_temporal_folds(
    frame: pl.DataFrame,
    folds: int,
    features: np.ndarray,
    *,
    require_balance: bool = False,
) -> tuple[dict[str, dict[str, np.ndarray]], dict[str, dict[str, object]]]:
    fold_scores: dict[str, dict[str, np.ndarray]] = {}
    fold_diagnostics: dict[str, dict[str, object]] = {}
    observations = ContrastObservations.from_frame(frame, features)
    temporal_folds = frame["fold"].to_numpy()
    for fold_name in ("train", "validation", "test"):
        subset = observations.select(temporal_folds == fold_name)
        unsupported = (
            len(subset.treatment) < 4
            or len(np.unique(subset.treatment)) < 2
            or len(np.unique(subset.match_ids)) < 2
        )
        if unsupported:
            if fold_name in SELECTION_FOLDS:
                raise ValueError(f"{fold_name} lacks cross-fitting support")
            continue
        propensity = (
            require_contrast_balance(subset, fold_name, folds)
            if require_balance and fold_name in SELECTION_FOLDS
            else None
        )
        result = _calculate_cross_fitted_scores(subset, folds, propensity)
        fold_scores[fold_name] = result
        treatment = result["treatment"]
        propensity = result["propensity"]
        observed_propensity = np.where(treatment == 1, propensity, 1 - propensity)
        weights = 1 / observed_propensity
        interval = _calculate_cluster_interval(result["influence"], result["match_ids"])
        fold_diagnostics[fold_name] = {
            "support": int(treatment.sum()),
            "comparison_support": int(len(treatment) - treatment.sum()),
            "effective_support": float(weights.sum() ** 2 / np.square(weights).sum()),
            "overlap": float(np.mean((propensity >= 0.1) & (propensity <= 0.9))),
            "maximum_weight": float(weights.max()),
            "maximum_standardized_mean_difference": _calculate_maximum_weighted_standardized_difference(
                result["features"], treatment, propensity
            ),
            "estimate": float(result["influence"].mean()),
            "interval": [float(interval[0]), float(interval[1])],
        }
    return fold_scores, fold_diagnostics


def estimate_cross_fitted_doubly_robust_contrast(
    decisions: pl.DataFrame,
    treatment_item_id: int,
    comparator_item_id: int,
    *,
    folds: int = 5,
    features: np.ndarray | None = None,
) -> DoublyRobustContrast:
    """Compare item outcomes at equivalent states with grouped cross-fitting and explicit evidence checks."""
    return _estimate_contrast(
        decisions,
        treatment_item_id,
        comparator_item_id,
        _EstimationOptions(folds, features),
    )


@dataclass(frozen=True)
class _EstimationOptions:
    folds: int = 5
    features: np.ndarray | None = None
    require_balance: bool = False


def estimate_admissible_contrast(
    decisions: pl.DataFrame,
    treatment_item_id: int,
    comparator_item_id: int,
    *,
    features: np.ndarray | None = None,
) -> DoublyRobustContrast | ContrastBalanceRejection:
    try:
        return _estimate_contrast(
            decisions,
            treatment_item_id,
            comparator_item_id,
            _EstimationOptions(features=features, require_balance=True),
        )
    except ContrastBalanceError as error:
        return error.rejection


def _estimate_contrast(
    decisions: pl.DataFrame,
    treatment_item_id: int,
    comparator_item_id: int,
    options: _EstimationOptions,
) -> DoublyRobustContrast:
    selected = decisions["item_id"].is_in([treatment_item_id, comparator_item_id])
    frame = decisions.filter(selected).with_columns(
        (pl.col("item_id") == treatment_item_id).cast(pl.Int8).alias("treatment")
    )
    matrix = (
        build_contrast_feature_matrix(frame)
        if options.features is None
        else options.features[selected.to_numpy()]
    )
    fold_scores, fold_diagnostics = _evaluate_temporal_folds(
        frame, options.folds, matrix, require_balance=options.require_balance
    )
    scores = {
        key: np.concatenate([fold_scores[fold][key] for fold in SELECTION_FOLDS])
        for key in next(iter(fold_scores.values()))
    }
    treatment = scores["treatment"]
    propensity = scores["propensity"]
    observed_propensity = np.where(treatment == 1, propensity, 1 - propensity)
    weights = 1 / observed_propensity
    effective_support = float(weights.sum() ** 2 / np.square(weights).sum())
    overlap = float(np.mean((propensity >= 0.1) & (propensity <= 0.9)))
    maximum_standardized_difference = (
        _calculate_maximum_weighted_standardized_difference(
            scores["features"], treatment, propensity
        )
    )
    estimate = float(scores["influence"].mean())
    interval = _calculate_cluster_interval(scores["influence"], scores["match_ids"])
    fold_estimates = {
        fold: number(diagnostics["estimate"])
        for fold, diagnostics in fold_diagnostics.items()
    }
    fold_intervals = {
        fold: cast("list[float]", fold_diagnostics[fold]["interval"])
        for fold in SELECTION_FOLDS
    }
    clipped_sensitivity = {}
    for clip in WEIGHT_CLIP_LIMITS:
        treated_weight = np.minimum(1 / propensity, clip)
        control_weight = np.minimum(1 / (1 - propensity), clip)
        treated_score = scores["outcome_treated"] + treatment * treated_weight * (
            scores["outcome"] - scores["outcome_treated"]
        )
        control_score = scores["outcome_control"] + (1 - treatment) * control_weight * (
            scores["outcome"] - scores["outcome_control"]
        )
        clipped_sensitivity[f"clip={clip:g}"] = float(
            np.mean(treated_score - control_score)
        )
    selection_estimates = [fold_estimates[fold] for fold in SELECTION_FOLDS]
    stable = max(selection_estimates) - min(selection_estimates) <= 0.05
    gates = {
        "support": all(
            min(
                integer(fold_diagnostics[fold]["support"]),
                integer(fold_diagnostics[fold]["comparison_support"]),
            )
            >= MINIMUM_SUPPORT
            for fold in SELECTION_FOLDS
        ),
        "effective_support": all(
            number(fold_diagnostics[fold]["effective_support"])
            >= MINIMUM_EFFECTIVE_SUPPORT
            for fold in SELECTION_FOLDS
        ),
        "overlap": all(
            number(fold_diagnostics[fold]["overlap"]) >= MINIMUM_OVERLAP
            for fold in SELECTION_FOLDS
        ),
        "balance": all(
            number(fold_diagnostics[fold]["maximum_standardized_mean_difference"])
            <= MAXIMUM_STANDARDIZED_MEAN_DIFFERENCE
            for fold in SELECTION_FOLDS
        ),
        "bounded_uncertainty": all(
            fold_intervals[fold][1] - fold_intervals[fold][0] <= MAXIMUM_INTERVAL_WIDTH
            for fold in SELECTION_FOLDS
        ),
        "positive_advantage": all(
            fold_intervals[fold][0] > 0 for fold in SELECTION_FOLDS
        ),
        "temporal_stability": stable,
    }
    support = sum(
        integer(fold_diagnostics[fold]["support"]) for fold in SELECTION_FOLDS
    )
    comparison_support = sum(
        integer(fold_diagnostics[fold]["comparison_support"])
        for fold in SELECTION_FOLDS
    )
    return DoublyRobustContrast(
        treatment_item_id=treatment_item_id,
        comparator_item_id=comparator_item_id,
        support=support,
        comparison_support=comparison_support,
        effective_support=effective_support,
        overlap=overlap,
        maximum_weight=float(weights.max()),
        maximum_standardized_mean_difference=maximum_standardized_difference,
        estimate=estimate,
        interval=interval,
        fold_estimates=fold_estimates,
        fold_diagnostics=fold_diagnostics,
        clipped_sensitivity=clipped_sensitivity,
        stable=stable,
        admitted=all(gates.values()),
        failed_gates=tuple(name for name, passed in gates.items() if not passed),
    )
