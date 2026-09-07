"""Keep frozen discovery pools and timing identical across artifact consumers."""

from __future__ import annotations

import math

from .artifacts import ArtifactError
from .build_evidence_values import _required_int
from .build_support import SUPPORT
from .value_validation import object_dict, object_list


def validate_frozen_pool(
    document: dict[str, object], discovery: dict[str, object]
) -> None:
    frozen = object_dict(discovery.get("frozen_guide")) or {}
    tier = object_dict(document.get("tier_policy")) or {}
    pool = object_dict(frozen.get("pool"))
    statistics = object_dict(frozen.get("pool_statistics"))
    if pool is None or statistics is None or set(pool) != {"1", "2", "3", "4"}:
        raise ArtifactError(
            "Frozen discovery has no complete item pool; refresh-evidence is required"
        )
    if (
        tier.get("item_ids_by_tier") != pool
        or tier.get("statistics") != statistics
        or tier.get("source_fold") != "discovery"
    ):
        raise ArtifactError("Item pool differs from frozen discovery evidence")
    population = _required_int(
        frozen.get("discovery_buyers"), "discovery buyers", minimum=SUPPORT.core_owners
    )
    seen: set[int] = set()
    path = object_list(frozen.get("path")) or []
    for raw in pool.values():
        items = object_list(raw)
        if items is None or len(items) > SUPPORT.pool_limit:
            raise ArtifactError("Frozen discovery pool exceeds its tier limits")
        for value in items:
            item = _required_int(value, "pool item", minimum=1)
            stats = object_dict(statistics.get(str(item))) or {}
            buyers = _required_int(
                stats.get("buyers"),
                "discovery item buyers",
                minimum=SUPPORT.pool_buyers,
            )
            adoption = stats.get("adoption")
            if (
                item in seen
                or item in path
                or buyers > population
                or not isinstance(adoption, (int, float))
                or not math.isclose(adoption, buyers / population)
            ):
                raise ArtifactError("Frozen item pool has invalid ownership support")
            seen.add(item)
    if document.get("purchase_timing") != frozen.get("purchase_timing"):
        raise ArtifactError("Purchase timing differs from the frozen item pool")
