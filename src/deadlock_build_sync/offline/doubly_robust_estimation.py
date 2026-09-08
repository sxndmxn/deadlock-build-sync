from __future__ import annotations

import math
from dataclasses import dataclass
from typing import cast

import numpy as np
import polars as pl
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from deadlock_build_sync.value_validation import integer, number

from .effect_estimation_limits import (
    MAXIMUM_INTERVAL_WIDTH,
    MAXIMUM_STANDARDIZED_MEAN_DIFFERENCE,
    MINIMUM_EFFECTIVE_SUPPORT,
    MINIMUM_OVERLAP,
    MINIMUM_SUPPORT,
    PROPENSITY_FLOOR,
    SELECTION_FOLDS,
    STATE_FEATURES,
    WEIGHT_CLIP_LIMITS,
)


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


def _build_feature_matrix(frame: pl.DataFrame) -> np.ndarray:
    columns = []
    extra = sorted(name for name in frame.columns if name.startswith("context_"))
    for feature in (*STATE_FEATURES, *extra):
        if feature in frame.columns:
            columns.append(
                frame[feature].cast(pl.Float64, strict=False).fill_nan(None).to_numpy()
            )
        else:
            columns.append(np.full(frame.height, np.nan))
    return np.column_stack(columns)


def _add_context_features(frame: pl.DataFrame) -> pl.DataFrame:
    columns = []
    for feature in ("enemy_heroes", "enemy_items", "owned_before"):
        if feature in frame.columns:
            groups = frame[feature].to_list()
            columns.extend(
                pl.Series(
                    f"context_{feature}_{item}",
                    [int(item in (group or [])) for group in groups],
                )
                for item in sorted({item for group in groups for item in (group or [])})
            )
    if (
        "relative_wealth" in frame.columns
        and frame["relative_wealth"].null_count() < frame.height
    ):
        columns.append(frame["relative_wealth"].alias("context_relative_wealth"))
    return frame.with_columns(columns)


def _fit_probability_model(
    features: np.ndarray, labels: np.ndarray
) -> Pipeline | float:
    if len(np.unique(labels)) < 2:
        return float((labels.sum() + 1) / (len(labels) + 2))
    model = Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median", keep_empty_features=True)),
            ("scale", StandardScaler()),
            ("model", LogisticRegression(C=0.5, max_iter=500, solver="lbfgs")),
        ],
        memory=None,
    )
    model.fit(features, labels)
    return model


def _predict_probabilities(model: Pipeline | float, features: np.ndarray) -> np.ndarray:
    if isinstance(model, Pipeline):
        return model.predict_proba(features)[:, 1]
    return np.full(len(features), float(model))


def _calculate_maximum_weighted_standardized_difference(
    features: np.ndarray, treatment: np.ndarray, propensity: np.ndarray
) -> float:
    maximum = 0.0
    weights = np.where(treatment == 1, 1 / propensity, 1 / (1 - propensity))
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


def _calculate_cross_fitted_scores(
    frame: pl.DataFrame, folds: int
) -> dict[str, np.ndarray]:
    features = _build_feature_matrix(frame)
    treatment = frame["treatment"].cast(int).to_numpy()
    outcome = frame["won"].cast(int).to_numpy()
    match_ids = frame["match_id"].cast(int).to_numpy()
    propensity = np.zeros(frame.height)
    outcome_treated = np.zeros(frame.height)
    outcome_control = np.zeros(frame.height)
    unique_matches = np.unique(match_ids)
    if len(unique_matches) < 2:
        raise ValueError("cross-fitting requires at least two match groups")
    assignments = {
        match_id: index % min(folds, len(unique_matches))
        for index, match_id in enumerate(unique_matches)
    }
    cross_fit_fold = np.array([assignments[match_id] for match_id in match_ids])
    for fold in range(folds):
        test = cross_fit_fold == fold
        train = ~test
        if not test.any():
            continue
        propensity_model = _fit_probability_model(features[train], treatment[train])
        propensity[test] = _predict_probabilities(propensity_model, features[test])
        for action, destination in (
            (1, outcome_treated),
            (0, outcome_control),
        ):
            action_train = train & (treatment == action)
            if not action_train.any():
                destination[test] = outcome[train].mean()
                continue
            outcome_model = _fit_probability_model(
                features[action_train], outcome[action_train]
            )
            destination[test] = _predict_probabilities(outcome_model, features[test])
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
    clusters = [
        influence[match_ids == match_id].mean() for match_id in np.unique(match_ids)
    ]
    if len(clusters) < 2:
        return estimate, estimate
    standard_error = float(np.std(clusters, ddof=1) / math.sqrt(len(clusters)))
    return estimate - 1.96 * standard_error, estimate + 1.96 * standard_error


def _evaluate_temporal_folds(
    frame: pl.DataFrame, folds: int
) -> tuple[dict[str, dict[str, np.ndarray]], dict[str, dict[str, object]]]:
    fold_scores: dict[str, dict[str, np.ndarray]] = {}
    fold_diagnostics: dict[str, dict[str, object]] = {}
    for fold_name in ("train", "validation", "test"):
        subset = frame.filter(pl.col("fold") == fold_name)
        unsupported = (
            subset.height < 4
            or subset["treatment"].n_unique() < 2
            or subset["match_id"].n_unique() < 2
        )
        if unsupported:
            if fold_name in SELECTION_FOLDS:
                raise ValueError(f"{fold_name} lacks cross-fitting support")
            continue
        result = _calculate_cross_fitted_scores(subset, folds)
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
) -> DoublyRobustContrast:
    """Compare item outcomes at equivalent states with grouped cross-fitting and explicit evidence checks."""
    frame = decisions.filter(
        pl.col("item_id").is_in([treatment_item_id, comparator_item_id])
    ).with_columns(
        (pl.col("item_id") == treatment_item_id).cast(pl.Int8).alias("treatment")
    )
    fold_scores, fold_diagnostics = _evaluate_temporal_folds(
        _add_context_features(frame), folds
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
