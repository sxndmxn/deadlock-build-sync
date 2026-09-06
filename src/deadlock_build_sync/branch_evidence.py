"""Verify branch diagnostics with the frozen family correction at installation."""

from __future__ import annotations

import math
from statistics import NormalDist

from .artifacts import ArtifactError
from .value_validation import object_dict, object_list


def diagnostic_number(row: dict[str, object], key: str) -> float:
    value = row.get(key)
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        raise ArtifactError(f"Automatic choice has invalid {key}")
    return float(value)


def validate_branch_diagnostics(
    evidence: dict[str, object], support: int, lower: float
) -> None:
    family = diagnostic_number(evidence, "hypotheses")
    folds = object_dict(evidence.get("fold_diagnostics"))
    if (
        family < 1
        or not family.is_integer()
        or folds is None
        or set(folds) != {"train", "validation"}
    ):
        raise ArtifactError(
            "Automatic choice has invalid validation folds or correction"
        )
    if (
        evidence.get("admitted") is not True
        or evidence.get("stable") is not True
        or evidence.get("failed_gates") != []
    ):
        raise ArtifactError("Automatic choice has failed comparison gates")
    critical = NormalDist().inv_cdf(1 - 0.025 / family)
    lowers, estimates, supports = [], [], []
    for value in folds.values():
        row = object_dict(value)
        if row is None:
            raise ArtifactError("Automatic choice has malformed fold diagnostics")
        estimate, corrected = _validate_fold(row, critical)
        estimates.append(estimate)
        lowers.append(corrected)
        supports.append(diagnostic_number(row, "support"))
    if (
        sum(supports) != support
        or max(estimates) - min(estimates) > 0.05
        or not math.isclose(min(lowers), lower)
    ):
        raise ArtifactError("Automatic choice has inconsistent corrected outcomes")


def _validate_fold(row: dict[str, object], critical: float) -> tuple[float, float]:
    interval = object_list(row.get("interval"))
    if interval is None or len(interval) != 2:
        raise ArtifactError("Automatic choice lacks a fold interval")
    low, high = [diagnostic_number({"value": value}, "value") for value in interval]
    estimate = diagnostic_number(row, "estimate")
    radius = (high - low) / 2 / 1.96 * critical
    valid = (
        min(
            diagnostic_number(row, "support"),
            diagnostic_number(row, "comparison_support"),
        )
        >= 20
        and diagnostic_number(row, "effective_support") >= 20
        and 0.5 <= diagnostic_number(row, "overlap") <= 1
        and 0 <= diagnostic_number(row, "maximum_standardized_mean_difference") <= 0.1
        and math.isclose((low + high) / 2, estimate, abs_tol=1e-12)
        and 0 <= radius <= 0.05
        and estimate - radius > 0
    )
    if not valid:
        raise ArtifactError(
            "Automatic choice lacks support, overlap, balance, or corrected outcome evidence"
        )
    return estimate, estimate - radius
