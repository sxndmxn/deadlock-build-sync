"""Validate the frozen discovery contract without importing analysis packages."""

from __future__ import annotations

import math

from .artifacts import ArtifactError
from .build_evidence_values import _required_int
from .value_validation import object_dict, object_list

DISCOVERY_METHOD = "eclat_leiden_pairwise"
REFRESH_INSTRUCTION = "Run deadlock-build-sync refresh-evidence, then build again."


def exclusion_reason(value: object) -> str:
    row = object_dict(value)
    if row is None or row.get("code") != "no_validated_identity":
        raise ArtifactError("Hero has no validated builds or supported exclusion")
    reason = row.get("reason")
    counts = object_dict(row.get("fold_observations"))
    if not isinstance(reason, str) or not reason.strip() or counts is None:
        raise ArtifactError("Hero exclusion has no reason or observation counts")
    for fold in ("discovery", "selection", "validation"):
        _required_int(counts.get(fold), f"{fold} exclusion observations")
    candidates = _required_int(row.get("candidate_count"), "excluded candidate count")
    rejections = object_list(row.get("candidate_rejections"))
    if rejections is None or (candidates and not rejections):
        raise ArtifactError("Hero exclusion lacks candidate rejection evidence")
    for rejection in rejections:
        if not isinstance(rejection, dict) or not rejection.get("reasons"):
            raise ArtifactError("Hero exclusion has an empty rejection reason")
    return reason.strip()


def discovery_rank(discovery: dict[str, object]) -> int:
    return _required_int(discovery.get("selection_rank"), "frozen selection rank")


def validate_discovery(
    discovery: dict[str, object], core: tuple[int, ...], path: tuple[int, ...]
) -> None:
    if (
        discovery.get("method") != DISCOVERY_METHOD
        or discovery.get("test_evaluated") is not False
    ):
        raise ArtifactError(f"Unsupported discovery evidence. {REFRESH_INSTRUCTION}")
    discovery_rank(discovery)
    if sorted(core) != discovery.get("items") or not 4 <= len(core) <= 6:
        raise ArtifactError("Discovery identity differs from the exact core")
    selection = object_dict(discovery.get("selection"))
    validation = object_dict(discovery.get("validation"))
    order = object_dict(discovery.get("path"))
    frozen = object_dict(discovery.get("frozen_guide"))
    if selection is None or validation is None or order is None or frozen is None:
        raise ArtifactError("Discovery is missing frozen admission evidence")
    if discovery.get("selection_rejections") != [] or discovery.get("rejections") != []:
        raise ArtifactError("A rejected discovery identity cannot be installed")
    hypotheses = _required_int(
        discovery.get("hypotheses"), "discovery hypotheses", minimum=1
    )
    for record in (selection, validation):
        _validate_outcome(record, hypotheses if record is validation else None)
    _validate_order(order, discovery.get("order_validation"), core, path, frozen)


def _validate_order(
    order: dict[str, object],
    validation: object,
    core: tuple[int, ...],
    path: tuple[int, ...],
    frozen: dict[str, object],
) -> None:
    for record in (
        order.get("discovery"),
        order.get("selection"),
        validation,
    ):
        if not isinstance(record, dict):
            raise ArtifactError("Discovery lacks purchase-order evidence")
        owners = _required_int(record.get("owners"), "order owners", minimum=100)
        support = _required_int(
            record.get("ordered_owners"), "ordered owners", minimum=20
        )
        if (
            support > owners
            or support / owners < 0.1
            or record.get("passes") is not True
        ):
            raise ArtifactError("Discovery purchase order lacks support")
    if (
        order.get("order") != list(core)
        or order.get("method") != "pairwise"
        or order.get("legal") is not True
        or order.get("admitted_before_validation") is not True
        or frozen.get("ready") is not True
        or frozen.get("path") != list(path)
    ):
        raise ArtifactError("Frozen discovery path differs from the admitted path")


def _numeric(row: dict[str, object], key: str) -> float:
    value = row.get(key)
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        raise ArtifactError(f"Discovery has invalid {key}")
    return float(value)


def _validate_outcome(row: dict[str, object], hypotheses: int | None) -> None:
    owners = _required_int(row.get("owners"), "core owners", minimum=100)
    wins = _required_int(row.get("wins"), "core wins")
    adjusted = object_dict(row.get("adjusted"))
    if (
        adjusted is None
        or wins > owners
        or not math.isclose(_numeric(row, "win_rate"), wins / owners)
    ):
        raise ArtifactError("Discovery has inconsistent core outcomes")
    valid = (
        wins / owners >= 0.52
        and _numeric(row, "joint_lift") >= 1.1
        and 100
        <= _required_int(adjusted.get("core_overlap"), "comparable core owners")
        <= owners
        and 0.8 <= _numeric(adjusted, "overlap_share") <= 1
    )
    if hypotheses is None:
        valid &= (
            _numeric(row, "win_lower_95") > 0.5 and _numeric(adjusted, "lower_95") > 0
        )
    else:
        threshold = 0.025 / hypotheses
        valid &= (
            0 <= _numeric(row, "win_p_greater_half") <= threshold
            and 0 <= _numeric(adjusted, "p_greater") <= threshold
            and _numeric(row, "adjusted_lower_family") > 0
        )
    if not valid:
        raise ArtifactError(
            "Discovery core does not pass its outcome and overlap gates"
        )


def frozen_windows(frozen: dict[str, object]) -> dict[int, tuple[float, float]]:
    bounds = object_dict(frozen.get("bounds"))
    if bounds is None:
        raise ArtifactError("Frozen guide has no purchase windows")
    result = {}
    for key, raw in bounds.items():
        window = object_list(raw)
        if not key.isdecimal() or int(key) <= 0 or window is None or len(window) != 2:
            raise ArtifactError("Frozen guide has malformed purchase windows")
        lower, upper = (_numeric({"value": value}, "value") for value in window)
        if not 0 <= lower <= upper:
            raise ArtifactError("Frozen guide has inverted purchase windows")
        result[int(key)] = (lower, upper)
    return result
