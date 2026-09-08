from __future__ import annotations

from dataclasses import dataclass

from .artifacts import ArtifactError
from .build_evidence_types import (
    MAX_COMPARATIVE_INTERVAL_WIDTH,
    THREAT_CLASSES,
    SituationalBranch,
)
from .build_evidence_values import (
    _require_boolean,
    _require_evidence_document,
    _require_finite_float,
    _require_float,
    _require_integer,
)
from .value_validation import object_dict

_FOLDS = ("train", "validation", "test")


@dataclass(frozen=True)
class _SituationalBranchIdentity:
    threat: str
    enemy_hero_id: int | None
    enemy_scope: str
    item_id: int
    comparator_item_id: int
    enemy_refs: tuple[str, ...]


@dataclass(frozen=True)
class _SituationalBranchSupport:
    comparison: int
    same_opportunity: bool
    support: int
    effective: float
    overlap: float
    stable: bool
    interval: tuple[float, float]


def _validate_situational_text(document: dict[str, object], hero_id: int) -> None:
    fields = (
        "mechanic_ref",
        "comparator",
        "trigger",
        "replacement",
        "execution",
        "failure_condition",
    )
    for field in fields:
        value = document.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ArtifactError(f"hero {hero_id} has an incomplete situational branch")


def _parse_enemy_references(
    document: dict[str, object], hero_id: int
) -> tuple[str, ...]:
    raw_refs = document.get("enemy_mechanics_refs")
    if not isinstance(raw_refs, list) or not raw_refs:
        raise ArtifactError(
            f"hero {hero_id} situational branch lacks enemy mechanics refs"
        )
    if not all(isinstance(ref, str) and ref.strip() for ref in raw_refs):
        raise ArtifactError(
            f"hero {hero_id} situational branch lacks enemy mechanics refs"
        )
    return tuple(str(ref).strip() for ref in raw_refs)


def _parse_situational_identity(
    document: dict[str, object], hero_id: int
) -> _SituationalBranchIdentity:
    threat = document.get("threat")
    enemy_scope = document.get("enemy_scope")
    if threat not in THREAT_CLASSES:
        raise ArtifactError(f"hero {hero_id} has an incomplete situational branch")
    if enemy_scope not in {"same_lane", "whole_enemy_team"}:
        raise ArtifactError(f"hero {hero_id} has an incomplete situational branch")
    _validate_situational_text(document, hero_id)
    enemy_hero_id = document.get("enemy_hero_id")
    if enemy_hero_id is not None:
        enemy_hero_id = _require_integer(enemy_hero_id, "enemy hero id", minimum=1)
    item_id = _require_integer(
        document.get("item_id"), "situational item id", minimum=1
    )
    comparator_id = _require_integer(
        document.get("comparator_item_id"),
        "situational comparator item id",
        minimum=1,
    )
    if comparator_id == item_id:
        raise ArtifactError(f"hero {hero_id} compares a situational item with itself")
    mechanic_ref = str(document["mechanic_ref"])
    if not mechanic_ref.startswith(f"item/{item_id}/"):
        raise ArtifactError(
            f"hero {hero_id} has a mismatched situational mechanic reference"
        )
    return _SituationalBranchIdentity(
        str(threat),
        enemy_hero_id,
        str(enemy_scope),
        item_id,
        comparator_id,
        _parse_enemy_references(document, hero_id),
    )


def _parse_comparative_interval(
    document: dict[str, object], hero_id: int
) -> tuple[float, float]:
    raw = document.get("comparative_interval")
    if not isinstance(raw, list) or len(raw) != 2:
        raise ArtifactError(
            f"hero {hero_id} has no bounded situational comparative interval"
        )
    lower = _require_float(raw[0], "situational interval lower")
    upper = _require_float(raw[1], "situational interval upper")
    if lower > upper or lower <= 0 or upper - lower > MAX_COMPARATIVE_INTERVAL_WIDTH:
        raise ArtifactError(
            f"hero {hero_id} has an unqualified situational comparative interval"
        )
    return lower, upper


def _parse_situational_support(
    document: dict[str, object], hero_id: int
) -> _SituationalBranchSupport:
    same_opportunity = _require_boolean(
        document.get("same_opportunity"), "situational same-opportunity gate"
    )
    comparison = _require_integer(
        document.get("comparison_support"),
        "situational comparison support",
        minimum=20,
    )
    support = _require_integer(
        document.get("support"), "situational support", minimum=20
    )
    effective = _require_float(
        document.get("effective_support"), "situational effective support", minimum=20
    )
    overlap = _require_float(
        document.get("overlap"), "situational overlap", maximum=1.0
    )
    stable = _require_boolean(document.get("stable"), "situational stability")
    interval = _parse_comparative_interval(document, hero_id)
    if overlap < 0.5 or not stable or not same_opportunity:
        raise ArtifactError(
            f"hero {hero_id} contains an unqualified situational branch"
        )
    return _SituationalBranchSupport(
        comparison,
        same_opportunity,
        support,
        effective,
        overlap,
        stable,
        interval,
    )


def _parse_situational_fold_evidence(
    document: dict[str, object], hero_id: int
) -> tuple[dict[str, float], dict[str, dict[str, int]]]:
    raw_estimates = object_dict(document.get("fold_comparative_estimates"))
    raw_support = object_dict(document.get("fold_support"))
    if raw_estimates is None or not set(raw_estimates) >= set(_FOLDS):
        raise ArtifactError(f"hero {hero_id} lacks situational fold evidence")
    if raw_support is None or not set(raw_support) >= set(_FOLDS):
        raise ArtifactError(f"hero {hero_id} lacks situational fold evidence")
    estimates = {
        fold: _require_finite_float(value, f"situational {fold} comparative estimate")
        for fold, value in raw_estimates.items()
    }
    support: dict[str, dict[str, int]] = {}
    for fold in _FOLDS:
        support_document = _require_evidence_document(
            raw_support[fold], f"hero {hero_id} lacks situational {fold} support"
        )
        support[fold] = {
            side: _require_integer(
                support_document.get(side),
                f"situational {fold} {side} support",
                minimum=20,
            )
            for side in ("item", "comparator")
        }
    stable = (
        estimates["train"] > 0
        and estimates["validation"] > 0
        and estimates["test"] > 0
        and abs(estimates["train"] - estimates["validation"]) <= 0.05
    )
    if not stable:
        raise ArtifactError(f"hero {hero_id} has unstable situational fold evidence")
    return estimates, support


def parse_situational_branch(value: object, hero_id: int) -> SituationalBranch:
    document = _require_evidence_document(
        value, f"hero {hero_id} has a malformed situational branch"
    )
    identity = _parse_situational_identity(document, hero_id)
    support = _parse_situational_support(document, hero_id)
    fold_estimates, fold_support = _parse_situational_fold_evidence(document, hero_id)
    return SituationalBranch(
        threat=identity.threat,
        item_id=identity.item_id,
        enemy_hero_id=identity.enemy_hero_id,
        enemy_scope=identity.enemy_scope,
        phase=_require_integer(document.get("phase"), "situational phase", maximum=3),
        tier=_require_integer(
            document.get("tier"), "situational decision tier", minimum=1, maximum=4
        ),
        mechanic_ref=str(document["mechanic_ref"]),
        enemy_mechanics_refs=identity.enemy_refs,
        fold_comparative_estimates=fold_estimates,
        fold_support=fold_support,
        comparator=str(document["comparator"]),
        comparator_item_id=identity.comparator_item_id,
        comparison_support=support.comparison,
        same_opportunity=support.same_opportunity,
        support=support.support,
        effective_support=support.effective,
        overlap=support.overlap,
        stable=support.stable,
        comparative_interval=support.interval,
        trigger=str(document["trigger"]),
        replacement=str(document["replacement"]),
        execution=str(document["execution"]),
        failure_condition=str(document["failure_condition"]),
    )
