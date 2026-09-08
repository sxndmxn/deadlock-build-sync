from __future__ import annotations

import math

from .artifacts import ArtifactError
from .build_evidence_types import (
    MAX_COMPARATIVE_INTERVAL_WIDTH,
    MINIMUM_CORE_SUPPORT,
    CoreAlternativeEvidence,
)
from .build_evidence_values import (
    _require_boolean,
    _require_evidence_document,
    _require_finite_float,
    _require_float,
    _require_integer,
)
from .value_validation import object_dict

_REQUIRED_FOLDS = frozenset({"train", "validation"})


def _parse_alternative_item_pair(
    document: dict[str, object],
    hero_id: int,
    item_ids: set[int],
    default_item_ids: set[int],
) -> tuple[int, int]:
    item_id = _require_integer(
        document.get("item_id"), "core alternative item id", minimum=1
    )
    comparator_id = _require_integer(
        document.get("comparator_item_id"),
        "core alternative comparator item id",
        minimum=1,
    )
    valid = (
        item_id in item_ids
        and item_id not in default_item_ids
        and comparator_id in default_item_ids
    )
    if not valid:
        raise ArtifactError(f"hero {hero_id} has an invalid core alternative pair")
    return item_id, comparator_id


def _validate_alternative_text(document: dict[str, object], hero_id: int) -> None:
    for field in ("vs", "why", "swap", "when", "skip"):
        value = document.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ArtifactError(f"hero {hero_id} has an incomplete core alternative")


def _parse_alternative_references(
    document: dict[str, object], hero_id: int
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    parsed: list[tuple[str, ...]] = []
    for field in ("mechanics_refs", "comparator_mechanics_refs"):
        value = document.get(field)
        if not isinstance(value, list) or not value:
            raise ArtifactError(f"hero {hero_id} core alternative lacks mechanics refs")
        if not all(isinstance(ref, str) and ref.strip() for ref in value):
            raise ArtifactError(f"hero {hero_id} core alternative lacks mechanics refs")
        parsed.append(tuple(str(ref).strip() for ref in value))
    return parsed[0], parsed[1]


def _parse_alternative_interval(
    document: dict[str, object], hero_id: int
) -> tuple[float, float, float]:
    raw_interval = document.get("comparative_interval")
    if not isinstance(raw_interval, list) or len(raw_interval) != 2:
        raise ArtifactError(f"hero {hero_id} core alternative lacks a DR interval")
    lower = _require_finite_float(raw_interval[0], "core alternative interval lower")
    upper = _require_finite_float(raw_interval[1], "core alternative interval upper")
    estimate = _require_finite_float(
        document.get("dr_estimate"), "core alternative DR estimate"
    )
    qualified = (
        lower <= upper
        and lower <= estimate <= upper
        and lower > 0
        and upper - lower <= MAX_COMPARATIVE_INTERVAL_WIDTH
    )
    if not qualified:
        raise ArtifactError(f"hero {hero_id} has an invalid core alternative interval")
    return lower, upper, estimate


def _parse_alternative_fold_estimates(
    document: dict[str, object], hero_id: int
) -> dict[str, float]:
    raw = object_dict(document.get("fold_estimates"))
    if raw is None or not set(raw) >= _REQUIRED_FOLDS:
        raise ArtifactError(f"hero {hero_id} core alternative lacks temporal estimates")
    return {
        fold: _require_finite_float(value, f"core alternative {fold} estimate")
        for fold, value in raw.items()
    }


def _parse_diagnostic_interval(
    diagnostics: dict[str, object], hero_id: int, fold: str
) -> tuple[float, float, float]:
    raw = diagnostics.get("interval")
    if not isinstance(raw, list) or len(raw) != 2:
        raise ArtifactError(f"hero {hero_id} core alternative lacks a {fold} interval")
    lower = _require_finite_float(raw[0], f"core alternative {fold} interval lower")
    upper = _require_finite_float(raw[1], f"core alternative {fold} interval upper")
    estimate = _require_finite_float(
        diagnostics.get("estimate"), f"core alternative {fold} estimate"
    )
    return lower, upper, estimate


def _parse_alternative_diagnostics(
    value: object,
    hero_id: int,
    fold: str,
    expected_estimate: float,
) -> dict[str, object]:
    diagnostics = _require_evidence_document(
        value, f"hero {hero_id} core alternative lacks {fold} diagnostics"
    )
    lower, upper, estimate = _parse_diagnostic_interval(diagnostics, hero_id, fold)
    support = _require_integer(
        diagnostics.get("support"),
        f"core alternative {fold} support",
        minimum=MINIMUM_CORE_SUPPORT,
    )
    comparison_support = _require_integer(
        diagnostics.get("comparison_support"),
        f"core alternative {fold} comparison support",
        minimum=MINIMUM_CORE_SUPPORT,
    )
    effective_support = _require_float(
        diagnostics.get("effective_support"),
        f"core alternative {fold} effective support",
        minimum=MINIMUM_CORE_SUPPORT,
    )
    overlap = _require_float(
        diagnostics.get("overlap"),
        f"core alternative {fold} overlap",
        maximum=1.0,
    )
    maximum_smd = _require_float(
        diagnostics.get("maximum_standardized_mean_difference"),
        f"core alternative {fold} balance",
    )
    qualified = (
        lower > 0
        and lower <= upper
        and lower <= estimate <= upper
        and upper - lower <= MAX_COMPARATIVE_INTERVAL_WIDTH
        and overlap >= 0.5
        and maximum_smd <= 0.1
        and math.isclose(expected_estimate, estimate, abs_tol=1e-12)
    )
    if not qualified:
        raise ArtifactError(
            f"hero {hero_id} contains an unqualified {fold} core alternative"
        )
    return {
        **diagnostics,
        "support": support,
        "comparison_support": comparison_support,
        "effective_support": effective_support,
        "overlap": overlap,
        "maximum_standardized_mean_difference": maximum_smd,
        "estimate": estimate,
        "interval": [lower, upper],
    }


def _parse_alternative_fold_evidence(
    document: dict[str, object], hero_id: int
) -> tuple[dict[str, float], dict[str, dict[str, object]]]:
    estimates = _parse_alternative_fold_estimates(document, hero_id)
    raw_diagnostics = object_dict(document.get("fold_diagnostics"))
    if raw_diagnostics is None or not set(raw_diagnostics) >= _REQUIRED_FOLDS:
        raise ArtifactError(f"hero {hero_id} core alternative lacks fold diagnostics")
    diagnostics = {
        fold: _parse_alternative_diagnostics(
            raw_diagnostics[fold], hero_id, fold, estimates[fold]
        )
        for fold in ("train", "validation")
    }
    if abs(estimates["train"] - estimates["validation"]) > 0.05:
        raise ArtifactError(f"hero {hero_id} has an unstable core alternative")
    return estimates, diagnostics


def _parse_alternative_support(
    document: dict[str, object], hero_id: int
) -> tuple[float, float, bool]:
    effective = _require_float(
        document.get("effective_support"),
        "core alternative effective support",
        minimum=MINIMUM_CORE_SUPPORT,
    )
    overlap = _require_float(
        document.get("overlap"), "core alternative overlap", maximum=1.0
    )
    stable = _require_boolean(document.get("stable"), "core alternative stability")
    if overlap < 0.5 or not stable:
        raise ArtifactError(f"hero {hero_id} contains an unqualified core alternative")
    return effective, overlap, stable


def parse_core_alternative(
    value: object,
    hero_id: int,
    item_ids: set[int],
    default_item_ids: set[int],
) -> CoreAlternativeEvidence:
    document = _require_evidence_document(
        value, f"hero {hero_id} has a malformed core alternative"
    )
    item_id, comparator_id = _parse_alternative_item_pair(
        document, hero_id, item_ids, default_item_ids
    )
    _validate_alternative_text(document, hero_id)
    refs, comparator_refs = _parse_alternative_references(document, hero_id)
    lower, upper, estimate = _parse_alternative_interval(document, hero_id)
    fold_estimates, fold_diagnostics = _parse_alternative_fold_evidence(
        document, hero_id
    )
    effective, overlap, stable = _parse_alternative_support(document, hero_id)
    return CoreAlternativeEvidence(
        item_id=item_id,
        comparator_item_id=comparator_id,
        stage=_require_integer(
            document.get("stage"), "core alternative stage", minimum=1
        ),
        support=_require_integer(
            document.get("support"),
            "core alternative support",
            minimum=MINIMUM_CORE_SUPPORT,
        ),
        comparison_support=_require_integer(
            document.get("comparison_support"),
            "core alternative comparison support",
            minimum=MINIMUM_CORE_SUPPORT,
        ),
        effective_support=effective,
        overlap=overlap,
        stable=stable,
        dr_estimate=estimate,
        comparative_interval=(lower, upper),
        vs=str(document["vs"]).strip(),
        why=str(document["why"]).strip(),
        swap=str(document["swap"]).strip(),
        when=str(document["when"]).strip(),
        skip=str(document["skip"]).strip(),
        mechanics_refs=refs,
        comparator_mechanics_refs=comparator_refs,
        fold_estimates=fold_estimates,
        fold_diagnostics=fold_diagnostics,
    )
