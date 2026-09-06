"""Freeze Eclat cores and Leiden groups using discovery and selection only."""

from __future__ import annotations

import hashlib
import json
import time
from operator import itemgetter

from .discovery_config import ARMS
from .discovery_data import HeroData
from .discovery_grouping import consolidate
from .discovery_mining import mine
from .discovery_quality import evaluate_core, rejection_reasons
from .discovery_types import Candidate, Catalog, DiscoveryReport


def identity_id(hero: int, items: list[int]) -> str:
    digest = hashlib.sha256(json.dumps(sorted(items)).encode()).hexdigest()[:16]
    return f"{hero}-{digest}"


def select(
    candidates: list[Candidate], groups: list[list[int]] | None = None
) -> list[int]:
    eligible = sorted(
        (
            index
            for index, row in enumerate(candidates)
            if not row["selection_rejections"]
        ),
        key=lambda index: (
            -(candidates[index]["selection"]["adjusted"]["lower_95"] or 0.0),
            -candidates[index]["selection"]["owners"],
            candidates[index]["items"],
        ),
    )
    if groups is None:
        return eligible[:3]
    membership = {
        index: group for group, members in enumerate(groups) for index in members
    }
    selected, used = [], set()
    for index in eligible:
        if membership[index] not in used:
            selected.append(index)
            used.add(membership[index])
    return selected[:3]


def discover_hero(data: HeroData, catalog: Catalog) -> DiscoveryReport:
    started = time.monotonic()
    discovery = data.mask("discovery")
    mining = mine(data.matrix[discovery], data.times[discovery], data.items, catalog)
    mine_seconds = time.monotonic() - started
    candidates = sorted(
        (row for row in mining["candidates"] if len(row["items"]) >= 4),
        key=itemgetter("items"),
    )
    started = time.monotonic()
    grouping = consolidate(candidates, data.matrix[discovery], data.items)
    group_seconds = time.monotonic() - started
    for row in candidates:
        row["identity_id"] = identity_id(data.hero, row["items"])
        row["selection"] = evaluate_core(data, tuple(row["items"]), "selection")
        row["selection_rejections"] = rejection_reasons(row["selection"])
    return {
        "sizes": mining["sizes"],
        "seeds": [row for row in mining["candidates"] if len(row["items"]) == 3],
        "candidates": candidates,
        "grouping": grouping,
        "mine_seconds": mine_seconds,
        "group_seconds": group_seconds,
        "selected": {
            ARMS[0]: select(candidates),
            ARMS[1]: select(candidates, grouping["groups"]),
        },
    }
