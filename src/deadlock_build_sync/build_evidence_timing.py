"""Admit strict adjacent purchase counts without inferring missing positions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .artifacts import ArtifactError
from .purchase_guidance_types import PurchaseTiming
from .value_validation import object_dict, object_list

if TYPE_CHECKING:
    from .build_evidence_types import ItemEvidence, SequencePolicy, TierPolicyEvidence


def _require_purchase_count(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ArtifactError("purchase timing counts must be nonnegative integers")
    return value


def parse_purchase_timing(
    value: object,
    sequence: SequencePolicy | None,
    tiers: TierPolicyEvidence,
    items: tuple[ItemEvidence, ...],
) -> tuple[PurchaseTiming, ...]:
    """Read the optional v1 extension; absence means timing is unknown.

    Returns:
        Validated counts for every selected pool item.

    Raises:
        ArtifactError: If the timing extension is incomplete or inconsistent.

    """
    if value is None:
        return ()
    data = object_dict(value)
    if data is None or type(data.get("version")) is not int or data.get("version") != 1:
        raise ArtifactError("purchase timing has an invalid version")
    path = object_list(data.get("core_path"))
    if (
        sequence is None
        or path is None
        or any(type(item) is not int for item in path)
        or data.get("core_path") != list(sequence.default_path)
        or data.get("fold") != "train"
    ):
        raise ArtifactError(
            "purchase timing differs from its core path or training fold"
        )
    raw = object_list(data.get("items"))
    if raw is None:
        raise ArtifactError("purchase timing has no item counts")
    pool_ids = {item for group in tiers.item_ids_by_tier.values() for item in group}
    evidence = {item.item_id: item for item in items}
    result: dict[int, PurchaseTiming] = {}
    for value_row in raw:
        timing = _parse_timing_row(
            value_row, pool_ids, evidence, len(sequence.default_path)
        )
        if timing.item_id in result:
            raise ArtifactError("purchase timing must cover each pool item once")
        result[timing.item_id] = timing
    if set(result) != pool_ids:
        raise ArtifactError("purchase timing must cover each pool item once")
    return tuple(result[item] for item in sorted(result))


def _parse_timing_row(
    value: object,
    pool_ids: set[int],
    evidence: dict[int, ItemEvidence],
    path_length: int,
) -> PurchaseTiming:
    row = object_dict(value)
    if row is None:
        raise ArtifactError("purchase timing contains a malformed item")
    item = _require_purchase_count(row.get("item_id"))
    buyers = _require_purchase_count(row.get("buyers"))
    counts = object_list(row.get("counts_by_checkpoint"))
    if item not in pool_ids or counts is None:
        raise ArtifactError("purchase timing must cover each pool item once")
    resolved = tuple(_require_purchase_count(count) for count in counts)
    if (
        buyers != evidence[item].training_adopter_matches
        or len(resolved) != path_length + 1
        or any(count > buyers for count in resolved)
    ):
        raise ArtifactError("purchase timing counts disagree with training evidence")
    return PurchaseTiming(item, buyers, resolved)
