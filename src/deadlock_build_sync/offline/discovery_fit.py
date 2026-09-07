"""Freeze Eclat cores and Leiden groups using discovery and selection only."""

from __future__ import annotations

import hashlib
import json
import time
from operator import itemgetter

from deadlock_build_sync.build_support import SUPPORT

from .discovery_config import ARMS
from .discovery_data import HeroData
from .discovery_grouping import consolidate
from .discovery_mining import mine
from .discovery_quality import evaluate_core
from .discovery_types import Candidate, Catalog, DiscoveryReport


def identity_id(hero: int, items: list[int]) -> str:
    digest = hashlib.sha256(json.dumps(sorted(items)).encode()).hexdigest()[:16]
    return f"{hero}-{digest}"


def select(candidates: list[Candidate]) -> list[int]:
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


def discover_hero(
    data: HeroData, catalog: Catalog, *, seeds: list[Candidate] | None = None
) -> DiscoveryReport:
    started = time.monotonic()
    discovery = data.mask("discovery")
    mining = (
        mine(data.matrix[discovery], data.times[discovery], data.items, catalog)
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
    grouping = consolidate(candidates, data.matrix[discovery], data.items)
    group_seconds = time.monotonic() - started
    for row in candidates:
        row["identity_id"] = identity_id(data.hero, row["items"])
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
            ARMS[0]: select(candidates),
            ARMS[1]: select(candidates),
        },
    }
