"""Select Eclat cores and Leiden groups before validation."""

from __future__ import annotations

import hashlib
import json
import time
from operator import itemgetter

from deadlock_build_sync.build_support import SUPPORT

from .discovery_config import DISCOVERY_METHODS
from .discovery_data import HeroDiscoveryData
from .discovery_grouping import group_core_candidates
from .discovery_mining import mine_core_candidates
from .discovery_quality import evaluate_core
from .discovery_types import (
    CoreDiscoveryCandidate,
    DiscoveryItemCatalog,
    DiscoveryReport,
)


def calculate_core_identity(hero: int, items: list[int]) -> str:
    digest = hashlib.sha256(json.dumps(sorted(items)).encode()).hexdigest()[:16]
    return f"{hero}-{digest}"


def rank_supported_candidates(candidates: list[CoreDiscoveryCandidate]) -> list[int]:
    return sorted(
        (
            index
            for index, row in enumerate(candidates)
            if not row["selection_rejections"]
        ),
        key=lambda index: (
            candidates[index]["selection"]["adjusted"]["lower_95"] is None,
            -(candidates[index]["selection"]["adjusted"]["lower_95"] or 0.0),
            -candidates[index]["selection"]["owners"],
            candidates[index]["items"],
        ),
    )


def discover_hero_cores(
    data: HeroDiscoveryData,
    catalog: DiscoveryItemCatalog,
    *,
    seeds: list[CoreDiscoveryCandidate] | None = None,
) -> DiscoveryReport:
    started = time.monotonic()
    discovery = data.fold_mask("discovery")
    mining = (
        mine_core_candidates(
            data.matrix[discovery], data.times[discovery], data.items, catalog
        )
        if seeds is None
        else {"candidates": seeds, "sizes": {}}
    )
    mine_seconds = time.monotonic() - started
    candidates = sorted(
        (
            row
            for row in mining["candidates"]
            if (len(row["items"]) == 3 if seeds is not None else len(row["items"]) >= 4)
        ),
        key=itemgetter("items"),
    )
    started = time.monotonic()
    grouping = group_core_candidates(candidates, data.matrix[discovery], data.items)
    group_seconds = time.monotonic() - started
    for row in candidates:
        row["identity_id"] = calculate_core_identity(data.hero, row["items"])
        row["selection"] = evaluate_core(data, tuple(row["items"]), "selection")
        row["selection_rejections"] = SUPPORT.core_reasons(
            row["discovery_support"], row["selection"]["owners"]
        )
    return {
        "sizes": mining["sizes"],
        "seeds": [row for row in mining["candidates"] if len(row["items"]) == 3],
        "candidates": candidates,
        "grouping": grouping,
        "mine_seconds": mine_seconds,
        "group_seconds": group_seconds,
        "selected": {
            DISCOVERY_METHODS[0]: rank_supported_candidates(candidates),
            DISCOVERY_METHODS[1]: rank_supported_candidates(candidates),
        },
    }
