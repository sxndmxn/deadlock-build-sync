"""Validate the frozen discovery contract without importing analysis packages."""

from __future__ import annotations

import math

from .artifacts import ArtifactError
from .build_evidence_values import _required_int
from .build_support import SUPPORT, OutcomeEvidence, outcome_limitations
from .build_support import numeric as _numeric
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
    if sorted(core) != discovery.get("items") or not 3 <= len(core) <= 6:
        raise ArtifactError("Discovery identity differs from the exact core")
    selection = object_dict(discovery.get("selection"))
    validation = object_dict(discovery.get("validation"))
    order = object_dict(discovery.get("path"))
    frozen = object_dict(discovery.get("frozen_guide"))
    if selection is None or validation is None or order is None or frozen is None:
        raise ArtifactError("Discovery is missing frozen admission evidence")
    if discovery.get("selection_rejections") != [] or discovery.get("rejections") != []:
        raise ArtifactError("A rejected discovery identity cannot be installed")
    outcome_supported = _validate_outcome_status(discovery, selection, validation)
    _validate_order(order, core, path, frozen)
    _order_record(discovery.get("order_validation"), required=outcome_supported)


def _validate_outcome_status(
    discovery: dict[str, object],
    selection: dict[str, object],
    validation: dict[str, object],
) -> bool:
    hypotheses = _required_int(
        discovery.get("hypotheses"), "discovery hypotheses", minimum=1
    )
    discovery_support = _required_int(
        discovery.get("discovery_support"), "discovery core owners"
    )
    selection_outcome = OutcomeEvidence.parse(selection)
    validation_outcome = OutcomeEvidence.parse(validation)
    if SUPPORT.core_reasons(discovery_support, selection_outcome.owners):
        raise ArtifactError("Discovery core lacks discovery or selection support")
    limitations = discovery.get("evidence_limitations")
    status = discovery.get("evidence_status")
    if status not in {"observed", "outcome_supported"} or not isinstance(
        limitations, list
    ):
        raise ArtifactError("Discovery has no evidence status or limitations")
    if status == "outcome_supported":
        if (
            limitations
            or outcome_limitations(selection_outcome)
            or outcome_limitations(validation_outcome, hypotheses)
        ):
            raise ArtifactError(
                "Discovery core does not pass its outcome and overlap gates"
            )
        if _numeric(validation, "adjusted_lower_family") <= 0:
            raise ArtifactError("Discovery outcome fails family correction")
    elif not limitations or any(
        not isinstance(reason, str) or not reason for reason in limitations
    ):
        raise ArtifactError("Observed discovery lacks evidence limitations")
    return status == "outcome_supported"


def _validate_order(
    order: dict[str, object],
    core: tuple[int, ...],
    path: tuple[int, ...],
    frozen: dict[str, object],
) -> None:
    for record in (order.get("discovery"), order.get("selection")):
        _order_record(record, required=True)
    if (
        order.get("order") != list(core)
        or (order.get("method"), order.get("legal")) != ("pairwise", True)
        or order.get("admitted_before_validation") is not True
        or frozen.get("ready") is not True
        or frozen.get("path") != list(path)
    ):
        raise ArtifactError("Frozen discovery path differs from the admitted path")


def _order_record(value: object, *, required: bool) -> None:
    record = object_dict(value)
    if record is None:
        raise ArtifactError("Discovery lacks purchase-order evidence")
    owners = _required_int(record.get("owners"), "order owners")
    support = _required_int(record.get("ordered_owners"), "ordered owners")
    passes = SUPPORT.order_supported(owners, support)
    if support > owners or not math.isclose(
        _numeric(record, "share"), support / max(1, owners)
    ):
        raise ArtifactError("Discovery purchase order has inconsistent counts")
    if record.get("passes") is not passes or (required and not passes):
        raise ArtifactError("Discovery purchase order lacks support")


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
