from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from itertools import chain, combinations
from typing import Any

import numpy as np
import polars as pl
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from deadlock_build_sync.mechanics import (
    BASE_INVENTORY_SLOTS,
    InventoryState,
    ItemGraph,
    MechanicsError,
    purchase_item,
    schedule_component_path,
)

MINIMUM_BACKBONE_SIZE = 4
MAXIMUM_BACKBONE_SIZE = 6
MINIMUM_SUPPORT = 20
MINIMUM_EXTENSION_RETENTION = 0.50
MAXIMUM_TEMPORAL_SHARE_RANGE = 0.10
MINIMUM_OVERLAP = 0.50
MAXIMUM_STANDARDIZED_MEAN_DIFFERENCE = 0.10
MAXIMUM_INTERVAL_WIDTH = 0.10
MINIMUM_EFFECTIVE_SUPPORT = 20.0
PROPENSITY_FLOOR = 0.05
CLIPS = (5.0, 10.0, 20.0)
CORE_TARGET_TOLERANCE_SHARE = 0.10
SELECTION_FOLDS = ("train", "validation")

STATE_FEATURES = (
    "average_badge",
    "phase",
    "buy_time",
    "own_net_worth_at_buy",
    "state_observed_at_s",
    "own_team_net_worth",
    "enemy_team_net_worth",
    "team_net_worth_lead",
    "state_age_s",
    "prior_catalog_spend",
    "prior_purchase_count",
)


@dataclass(frozen=True)
class BackboneSelection:
    item_ids: tuple[int, ...]
    matches: int
    fold_matches: dict[str, int]
    audit: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class DrContrast:
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
    fold_diagnostics: dict[str, dict[str, Any]]
    clipped_sensitivity: dict[str, float]
    stable: bool
    admitted: bool
    failed_gates: tuple[str, ...]


def _legal_target(graph: ItemGraph, item_ids: tuple[int, ...]) -> bool:
    priorities = {item_id: (0.0, 0.0, item_id) for item_id in graph.nodes}
    try:
        path = schedule_component_path(graph, item_ids, priorities)
        state = InventoryState()
        for item_id in path:
            state = purchase_item(graph, state, item_id)
    except (KeyError, MechanicsError):
        return False
    return len(path) == len(set(path)) and set(state.owned) == set(item_ids)


type _BackboneRow = tuple[tuple[int, ...], int, dict[str, int]]


def _bundle_support_by_size_and_fold(
    inventories: dict[tuple[int, int], tuple[int, ...]],
    folds_by_match: dict[int, str],
    excluded_item_ids: frozenset[int],
) -> dict[int, dict[str, Counter[tuple[int, ...]]]]:
    inventories_by_fold: dict[str, list[tuple[int, ...]]] = {
        fold: [] for fold in ("train", "validation", "test")
    }
    for (match_id, _), inventory in inventories.items():
        distinct = tuple(sorted(set(inventory) - excluded_item_ids))
        if len(distinct) < MINIMUM_BACKBONE_SIZE:
            continue
        inventories_by_fold[folds_by_match[match_id]].append(distinct)
    result: dict[int, dict[str, Counter[tuple[int, ...]]]] = {}
    for size in range(MINIMUM_BACKBONE_SIZE, MAXIMUM_BACKBONE_SIZE + 1):
        fold_counts: dict[str, Counter[tuple[int, ...]]] = {}
        for fold, fold_inventories in inventories_by_fold.items():
            fold_counts[fold] = Counter(
                chain.from_iterable(
                    combinations(inventory, size)
                    for inventory in fold_inventories
                    if len(inventory) >= size
                )
            )
        result[size] = fold_counts
    return result


def _qualified_backbones_at_size(
    size: int,
    fold_counts: dict[str, Counter[tuple[int, ...]]],
    fold_totals: Counter[str],
    graph: ItemGraph,
    affinity: dict[int, int],
    minimum_support: int,
    audit: list[dict[str, Any]],
) -> list[_BackboneRow]:
    qualified = []
    ranked = sorted(fold_counts["train"].items(), key=lambda row: (-row[1], row[0]))[
        :256
    ]
    for item_ids, training_support in ranked:
        if training_support < minimum_support:
            break
        fold_matches = {
            fold: matches[item_ids] for fold, matches in fold_counts.items()
        }
        support = sum(fold_matches[fold] for fold in SELECTION_FOLDS)
        fold_shares = [
            fold_matches[fold] / fold_totals[fold]
            for fold in SELECTION_FOLDS
            if fold_totals[fold]
        ]
        gates = {
            "mechanically_legal": _legal_target(graph, item_ids),
            "effective_support": all(
                fold_matches[fold] >= minimum_support for fold in SELECTION_FOLDS
            ),
            "temporally_stable": bool(fold_shares)
            and max(fold_shares) - min(fold_shares) <= MAXIMUM_TEMPORAL_SHARE_RANGE,
        }
        admitted = all(gates.values())
        audit.append({
            "item_ids": list(item_ids),
            "size": size,
            "matches": support,
            "fold_matches": fold_matches,
            "mechanic_affinity": sum(affinity.get(item_id, 0) for item_id in item_ids),
            "gates": gates,
            "admitted": admitted,
        })
        if admitted:
            qualified.append((item_ids, support, fold_matches))
    return sorted(
        qualified,
        key=lambda row: (
            -row[1],
            -sum(affinity.get(item_id, 0) for item_id in row[0]),
            row[0],
        ),
    )


def select_supported_backbone(
    inventories: dict[tuple[int, int], tuple[int, ...]],
    folds_by_match: dict[int, str],
    graph: ItemGraph,
    *,
    minimum_support: int = MINIMUM_SUPPORT,
    excluded_item_ids: frozenset[int] = frozenset(),
    mechanic_affinity: dict[int, int] | None = None,
) -> BackboneSelection:
    """Select the longest stable bundle before support falls off an empirical cliff."""
    affinity = mechanic_affinity or {}
    fold_totals = Counter(folds_by_match[identity[0]] for identity in inventories)
    ranked_by_size: dict[int, list[tuple[tuple[int, ...], int, dict[str, int]]]] = {}
    audit: list[dict[str, Any]] = []
    fold_counts_by_size = _bundle_support_by_size_and_fold(
        inventories,
        folds_by_match,
        excluded_item_ids,
    )
    for size in range(MINIMUM_BACKBONE_SIZE, MAXIMUM_BACKBONE_SIZE + 1):
        ranked_by_size[size] = _qualified_backbones_at_size(
            size,
            fold_counts_by_size[size],
            fold_totals,
            graph,
            affinity,
            minimum_support,
            audit,
        )
    if not ranked_by_size[MINIMUM_BACKBONE_SIZE]:
        raise RuntimeError("hero has no mechanically legal, temporally stable backbone")
    selected = ranked_by_size[MINIMUM_BACKBONE_SIZE][0]
    for size in range(MINIMUM_BACKBONE_SIZE + 1, MAXIMUM_BACKBONE_SIZE + 1):
        extensions = [
            row
            for row in ranked_by_size[size]
            if set(selected[0]) < set(row[0])
            and row[1] / selected[1] >= MINIMUM_EXTENSION_RETENTION
        ]
        if not extensions:
            break
        selected = min(
            extensions,
            key=lambda row: (
                -row[1],
                -sum(affinity.get(item_id, 0) for item_id in row[0]),
                row[0],
            ),
        )
    return BackboneSelection(
        item_ids=selected[0],
        matches=selected[1],
        fold_matches=selected[2],
        audit=tuple(audit),
    )


type _CompletionScore = tuple[int, tuple[float, float], tuple[int, ...], int]


def _addition_support(
    backbone: BackboneSelection,
    supporting: dict[tuple[int, int], tuple[int, ...]],
    folds_by_match: dict[int, str],
    excluded_item_ids: frozenset[int],
) -> tuple[Counter[int], dict[str, Counter[int]], list[int]]:
    item_counts: Counter[int] = Counter()
    fold_item_counts = {fold: Counter() for fold in ("train", "validation", "test")}
    backbone_ids = set(backbone.item_ids)
    for (match_id, _), inventory in supporting.items():
        additions = set(inventory) - backbone_ids - excluded_item_ids
        item_counts.update(additions)
        fold_item_counts[folds_by_match[match_id]].update(additions)
    selection_counts = fold_item_counts["train"] + fold_item_counts["validation"]
    ranked = sorted(
        fold_item_counts["train"],
        key=lambda item_id: (-fold_item_counts["train"][item_id], item_id),
    )
    return selection_counts, fold_item_counts, ranked[:20]


def _joint_addition_support(
    backbone: BackboneSelection,
    supporting: dict[tuple[int, int], tuple[int, ...]],
    folds_by_match: dict[int, str],
    pool: list[int],
) -> tuple[
    dict[int, Counter[tuple[int, ...]]],
    dict[int, dict[str, Counter[tuple[int, ...]]]],
]:
    pool_set = set(pool)
    backbone_ids = set(backbone.item_ids)
    joint_counts: dict[int, Counter[tuple[int, ...]]] = {}
    joint_fold_counts: dict[int, dict[str, Counter[tuple[int, ...]]]] = {}
    for needed in range(BASE_INVENTORY_SLOTS - len(backbone.item_ids) + 1):
        counts: Counter[tuple[int, ...]] = Counter()
        fold_counts = {fold: Counter() for fold in ("train", "validation", "test")}
        for (match_id, _), inventory in supporting.items():
            available = tuple(sorted((set(inventory) - backbone_ids) & pool_set))
            if len(available) < needed:
                continue
            bundles = tuple(combinations(available, needed))
            counts.update(bundles)
            fold_counts[folds_by_match[match_id]].update(bundles)
        joint_counts[needed] = fold_counts["train"]
        joint_fold_counts[needed] = fold_counts
    return joint_counts, joint_fold_counts


def _completion_target_metrics(
    total_cost: int, target_cost: int | None
) -> tuple[int | None, bool | None]:
    if target_cost is None:
        return None, None
    distance = abs(total_cost - target_cost)
    return distance, distance <= target_cost * CORE_TARGET_TOLERANCE_SHARE


def _evaluate_completion(
    backbone: BackboneSelection,
    additions: tuple[int, ...],
    joint: int,
    joint_fold_matches: dict[str, int],
    supporting_fold_totals: Counter[str],
    item_counts: Counter[int],
    fold_item_counts: dict[str, Counter[int]],
    graph: ItemGraph,
    item_costs: dict[int, int],
    maximum_cost: int,
    target_cost: int | None,
) -> tuple[dict[str, Any], _CompletionScore | None]:
    target = (*backbone.item_ids, *additions)
    fold_shares = [
        joint_fold_matches[fold] / supporting_fold_totals[fold]
        for fold in SELECTION_FOLDS
        if supporting_fold_totals[fold]
    ]
    total_cost = sum(item_costs.get(item_id, maximum_cost + 1) for item_id in target)
    gates = {
        "mechanically_legal": _legal_target(graph, target),
        "within_cohort_wealth": total_cost <= maximum_cost,
        "conditional_support": all(
            item_counts[item_id] >= MINIMUM_SUPPORT for item_id in additions
        ),
        "temporal_support": all(
            fold_item_counts[fold][item_id] >= MINIMUM_SUPPORT
            for fold in SELECTION_FOLDS
            for item_id in additions
        ),
        "joint_effective_support": all(
            joint_fold_matches[fold] >= MINIMUM_SUPPORT for fold in SELECTION_FOLDS
        ),
        "joint_temporal_stability": bool(fold_shares)
        and max(fold_shares) - min(fold_shares) <= MAXIMUM_TEMPORAL_SHARE_RANGE,
    }
    supports = tuple(item_counts[item_id] for item_id in additions)
    if supports:
        conditional_score = float(min(supports)), sum(supports) / len(supports)
    else:
        conditional_score = float(backbone.matches), float(backbone.matches)
    distance, within_band = _completion_target_metrics(total_cost, target_cost)
    admitted = all(gates.values())
    record = {
        "item_ids": list(target),
        "added_item_ids": list(additions),
        "conditional_support": {
            str(item_id): item_counts[item_id] for item_id in additions
        },
        "joint_matches": joint,
        "joint_fold_matches": joint_fold_matches,
        "total_cost": total_cost,
        "target_cost": target_cost,
        "target_distance": distance,
        "within_target_band": within_band,
        "gates": gates,
        "admitted": admitted,
    }
    score = (joint, conditional_score, additions, total_cost) if admitted else None
    return record, score


def _eligible_completions(
    candidates: list[_CompletionScore], target_cost: int | None
) -> list[_CompletionScore]:
    if target_cost is None:
        return candidates
    in_band = [
        row
        for row in candidates
        if abs(row[3] - target_cost) <= target_cost * CORE_TARGET_TOLERANCE_SHARE
    ]
    if in_band:
        return in_band
    closest_distance = min(abs(row[3] - target_cost) for row in candidates)
    return [row for row in candidates if abs(row[3] - target_cost) == closest_distance]


def complete_default_core(
    backbone: BackboneSelection,
    inventories: dict[tuple[int, int], tuple[int, ...]],
    folds_by_match: dict[int, str],
    graph: ItemGraph,
    item_costs: dict[int, int],
    maximum_cost: int,
    *,
    excluded_item_ids: frozenset[int] = frozenset(),
    target_cost: int | None = None,
) -> tuple[tuple[int, ...], int, tuple[dict[str, Any], ...]]:
    """Complete the backbone near the economy target while reserving situational room."""
    supporting = {
        identity: inventory
        for identity, inventory in inventories.items()
        if set(backbone.item_ids) <= set(inventory)
    }
    item_counts, fold_item_counts, pool = _addition_support(
        backbone, supporting, folds_by_match, excluded_item_ids
    )
    joint_counts, joint_fold_counts = _joint_addition_support(
        backbone, supporting, folds_by_match, pool
    )
    supporting_fold_totals = Counter(
        folds_by_match[identity[0]] for identity in supporting
    )
    candidates: list[_CompletionScore] = []
    audit: list[dict[str, Any]] = []
    for needed in joint_counts:
        for additions in combinations(pool, needed):
            bundle = tuple(sorted(additions))
            joint_fold_matches = {
                fold: fold_counts[bundle]
                for fold, fold_counts in joint_fold_counts[needed].items()
            }
            joint = sum(joint_fold_matches[fold] for fold in SELECTION_FOLDS)
            record, score = _evaluate_completion(
                backbone,
                additions,
                joint,
                joint_fold_matches,
                supporting_fold_totals,
                item_counts,
                fold_item_counts,
                graph,
                item_costs,
                maximum_cost,
                target_cost,
            )
            audit.append(record)
            if score is not None:
                candidates.append(score)
    if not candidates:
        raise RuntimeError("hero backbone has no supported legal core completion")
    eligible = _eligible_completions(candidates, target_cost)
    joint, _, additions, _ = max(
        eligible,
        key=lambda row: (row[0], row[1], tuple(-item for item in row[2])),
    )
    selected_ids = {*backbone.item_ids, *additions}
    selected_audit = next(
        row
        for row in audit
        if bool(row["admitted"]) and set(row["item_ids"]) == selected_ids
    )
    selected_audit["selected"] = True
    ranked_audit = sorted(
        audit,
        key=lambda row: (
            not bool(row["admitted"]),
            -sum(int(value) for value in row["conditional_support"].values()),
            tuple(int(item_id) for item_id in row["item_ids"]),
        ),
    )
    bounded_audit = [selected_audit]
    bounded_audit.extend(row for row in ranked_audit if row is not selected_audit)
    bounded_audit = bounded_audit[:128]
    return (*backbone.item_ids, *additions), joint, tuple(bounded_audit)


def _matrix(frame: pl.DataFrame) -> np.ndarray:
    columns = []
    for feature in STATE_FEATURES:
        if feature in frame.columns:
            columns.append(
                frame[feature].cast(pl.Float64, strict=False).fill_nan(None).to_numpy()
            )
        else:
            columns.append(np.full(frame.height, np.nan))
    return np.column_stack(columns)


def _probability_model(x: np.ndarray, y: np.ndarray) -> Pipeline | float:
    if len(np.unique(y)) < 2:
        return float((y.sum() + 1) / (len(y) + 2))
    model = Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median")),
            ("scale", StandardScaler()),
            ("model", LogisticRegression(C=0.5, max_iter=500, solver="lbfgs")),
        ],
        memory=None,
    )
    model.fit(x, y)
    return model


def _predict(model: Pipeline | float, x: np.ndarray) -> np.ndarray:
    if isinstance(model, Pipeline):
        return model.predict_proba(x)[:, 1]
    return np.full(len(x), float(model))


def _weighted_smd(
    x: np.ndarray, treatment: np.ndarray, propensity: np.ndarray
) -> float:
    maximum = 0.0
    weights = np.where(treatment == 1, 1 / propensity, 1 / (1 - propensity))
    for column in range(x.shape[1]):
        values = x[:, column]
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
    return maximum


def _cross_fitted_scores(frame: pl.DataFrame, folds: int) -> dict[str, np.ndarray]:
    x = _matrix(frame)
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
    microfold = np.array([assignments[match_id] for match_id in match_ids])
    for fold in range(folds):
        test = microfold == fold
        train = ~test
        if not test.any():
            continue
        propensity_model = _probability_model(x[train], treatment[train])
        propensity[test] = _predict(propensity_model, x[test])
        for action, destination in (
            (1, outcome_treated),
            (0, outcome_control),
        ):
            action_train = train & (treatment == action)
            if not action_train.any():
                destination[test] = outcome[train].mean()
                continue
            outcome_model = _probability_model(x[action_train], outcome[action_train])
            destination[test] = _predict(outcome_model, x[test])
    propensity = np.clip(propensity, PROPENSITY_FLOOR, 1 - PROPENSITY_FLOOR)
    score_treated = outcome_treated + treatment / propensity * (
        outcome - outcome_treated
    )
    score_control = outcome_control + (1 - treatment) / (1 - propensity) * (
        outcome - outcome_control
    )
    return {
        "x": x,
        "treatment": treatment,
        "outcome": outcome,
        "propensity": propensity,
        "influence": score_treated - score_control,
        "match_ids": match_ids,
        "outcome_treated": outcome_treated,
        "outcome_control": outcome_control,
    }


def _cluster_interval(
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


def cross_fitted_dr_contrast(
    decisions: pl.DataFrame,
    treatment_item_id: int,
    comparator_item_id: int,
    *,
    folds: int = 5,
) -> DrContrast:
    """Estimate a like-state item contrast with grouped cross-fitting and hard gates."""
    frame = decisions.filter(
        pl.col("item_id").is_in([treatment_item_id, comparator_item_id])
    ).with_columns(
        (pl.col("item_id") == treatment_item_id).cast(pl.Int8).alias("treatment")
    )
    fold_scores: dict[str, dict[str, np.ndarray]] = {}
    fold_diagnostics: dict[str, dict[str, Any]] = {}
    for fold_name in ("train", "validation", "test"):
        subset = frame.filter(pl.col("fold") == fold_name)
        if (
            subset.height < 4
            or subset["treatment"].n_unique() < 2
            or subset["match_id"].n_unique() < 2
        ):
            if fold_name in SELECTION_FOLDS:
                raise ValueError(f"{fold_name} lacks cross-fitting support")
            continue
        result = _cross_fitted_scores(subset, folds)
        fold_scores[fold_name] = result
        fold_treatment = result["treatment"]
        fold_propensity = result["propensity"]
        fold_observed_propensity = np.where(
            fold_treatment == 1, fold_propensity, 1 - fold_propensity
        )
        fold_weights = 1 / fold_observed_propensity
        fold_interval = _cluster_interval(result["influence"], result["match_ids"])
        fold_diagnostics[fold_name] = {
            "support": int(fold_treatment.sum()),
            "comparison_support": int(len(fold_treatment) - fold_treatment.sum()),
            "effective_support": float(
                fold_weights.sum() ** 2 / np.square(fold_weights).sum()
            ),
            "overlap": float(
                np.mean((fold_propensity >= 0.1) & (fold_propensity <= 0.9))
            ),
            "maximum_weight": float(fold_weights.max()),
            "maximum_standardized_mean_difference": _weighted_smd(
                result["x"], fold_treatment, fold_propensity
            ),
            "estimate": float(result["influence"].mean()),
            "interval": [float(fold_interval[0]), float(fold_interval[1])],
        }
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
    maximum_smd = _weighted_smd(scores["x"], treatment, propensity)
    estimate = float(scores["influence"].mean())
    interval = _cluster_interval(scores["influence"], scores["match_ids"])
    fold_estimates = {
        fold: float(diagnostics["estimate"])
        for fold, diagnostics in fold_diagnostics.items()
    }
    clipped_sensitivity = {}
    for clip in CLIPS:
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
                int(fold_diagnostics[fold]["support"]),
                int(fold_diagnostics[fold]["comparison_support"]),
            )
            >= MINIMUM_SUPPORT
            for fold in SELECTION_FOLDS
        ),
        "effective_support": all(
            float(fold_diagnostics[fold]["effective_support"])
            >= MINIMUM_EFFECTIVE_SUPPORT
            for fold in SELECTION_FOLDS
        ),
        "overlap": all(
            float(fold_diagnostics[fold]["overlap"]) >= MINIMUM_OVERLAP
            for fold in SELECTION_FOLDS
        ),
        "balance": all(
            float(fold_diagnostics[fold]["maximum_standardized_mean_difference"])
            <= MAXIMUM_STANDARDIZED_MEAN_DIFFERENCE
            for fold in SELECTION_FOLDS
        ),
        "bounded_uncertainty": all(
            float(fold_diagnostics[fold]["interval"][1])
            - float(fold_diagnostics[fold]["interval"][0])
            <= MAXIMUM_INTERVAL_WIDTH
            for fold in SELECTION_FOLDS
        ),
        "positive_advantage": all(
            float(fold_diagnostics[fold]["interval"][0]) > 0 for fold in SELECTION_FOLDS
        ),
        "temporal_stability": stable,
    }
    support = sum(int(fold_diagnostics[fold]["support"]) for fold in SELECTION_FOLDS)
    comparison_support = sum(
        int(fold_diagnostics[fold]["comparison_support"]) for fold in SELECTION_FOLDS
    )
    return DrContrast(
        treatment_item_id=treatment_item_id,
        comparator_item_id=comparator_item_id,
        support=support,
        comparison_support=comparison_support,
        effective_support=effective_support,
        overlap=overlap,
        maximum_weight=float(weights.max()),
        maximum_standardized_mean_difference=maximum_smd,
        estimate=estimate,
        interval=interval,
        fold_estimates=fold_estimates,
        fold_diagnostics=fold_diagnostics,
        clipped_sensitivity=clipped_sensitivity,
        stable=stable,
        admitted=all(gates.values()),
        failed_gates=tuple(name for name, passed in gates.items() if not passed),
    )
