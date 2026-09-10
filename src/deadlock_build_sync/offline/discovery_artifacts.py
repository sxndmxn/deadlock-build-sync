"""Build item pool evidence and purchase artifacts for each exact core."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .sql_resources import load_sql

if TYPE_CHECKING:
    import duckdb

import polars as pl

from deadlock_build_sync.build_evidence import (
    CORE_POLICY_VERSION,
    SEQUENCE_POLICY_VERSION,
    SITUATIONAL_POLICY_VERSION,
    THREAT_CLASSES,
    TIER_POLICY_VERSION,
)
from deadlock_build_sync.build_evidence_types import nondecreasing_window_schedule
from deadlock_build_sync.build_support import SUPPORT
from deadlock_build_sync.mechanics import (
    ItemGraph,
    MechanicsError,
    schedule_component_path,
)
from deadlock_build_sync.purchase_planner import plan_purchases

from .discovery_admission import build_discovery_record
from .discovery_data import HeroDiscoveryData
from .discovery_ownership import calculate_core_ownership_mask
from .discovery_pool import (
    calculate_purchase_timing_policy,
    summarize_purchase_evidence,
)
from .discovery_types import FrozenPurchaseGuide, ItemPoolEvidence, NominatedCoreBuild
from .production_items import _build_item_evidence_payload, _query_path_cohort_summary
from .production_sources import _query_path_item_metrics
from .production_timing import _count_purchase_intervals


def select_core_owners(
    data: HeroDiscoveryData, core: list[int], fold: str | None = None
) -> frozenset[tuple[int, int]]:
    columns = tuple(data.items.index(item) for item in core)
    mask = calculate_core_ownership_mask(data.matrix, columns)
    if fold is not None:
        mask &= data.fold_mask(fold)
    else:
        mask &= data.fold_mask("discovery") | data.fold_mask("validation")
    return frozenset(
        actor for actor, included in zip(data.actors, mask, strict=True) if included
    )


def load_item_pool_evidence(
    connection: duckdb.DuckDBPyConnection, members: frozenset[tuple[int, int]]
) -> ItemPoolEvidence:
    connection.register(
        "_discovery_buyers",
        pl.DataFrame({
            "match_id": [actor[0] for actor in members],
            "player_slot": [actor[1] for actor in members],
        }),
    )
    try:
        rows = connection.execute(
            load_sql("discovery/select_item_pool_purchases.sql")
        ).fetchall()
    finally:
        connection.unregister("_discovery_buyers")
    return summarize_purchase_evidence(rows, len(members))


def select_tier_item_pool(
    graph: ItemGraph, evidence: ItemPoolEvidence, path: tuple[int, ...]
) -> dict[str, list[int]]:
    ranked = sorted(
        (
            item
            for item, stats in evidence["items"].items()
            if item in graph.nodes
            and item not in path
            and stats["buyers"] >= SUPPORT.pool_buyers
        ),
        key=lambda item: (-evidence["items"][item]["buyers"], item),
    )
    return {
        str(tier): sorted(
            [item for item in ranked if graph.require(item).tier == tier][
                : SUPPORT.pool_limit
            ],
            key=lambda item: (
                evidence["items"][item]["time_seconds_q25_q50_q75"][1],
                item,
            ),
        )
        for tier in range(1, 5)
    }


def freeze_purchase_guide(
    connection: duckdb.DuckDBPyConnection,
    data: HeroDiscoveryData,
    row: NominatedCoreBuild,
    graph: ItemGraph,
    *,
    exact_path: tuple[int, ...] | None = None,
) -> FrozenPurchaseGuide:
    evidence = load_item_pool_evidence(
        connection, select_core_owners(data, row["items"], "discovery")
    )
    order = tuple(row["path"]["order"])
    if not order:
        return {"ready": False, "reason": "No supported purchase order"}
    priorities, bounds = calculate_purchase_timing_policy(evidence["items"])
    try:
        path = (
            exact_path
            if exact_path is not None
            else schedule_component_path(graph, order, priorities)
        )
        plan = plan_purchases(graph, path, tuple(row["items"]), {})
    except (MechanicsError, ValueError) as error:
        return {"ready": False, "reason": str(error)}
    if tuple(step.item_id for step in plan.actions) != path:
        return {
            "ready": False,
            "reason": "Component planner differs from the frozen route",
        }
    uncertain = nondecreasing_window_schedule(path, bounds) is None
    pool = select_tier_item_pool(graph, evidence, path)
    missing = {
        item
        for item in path
        if evidence["items"].get(item, {}).get("buyers", 0) < SUPPORT.pool_buyers
    }
    if missing:
        return {
            "ready": False,
            "reason": f"Incomplete component purchase records: {sorted(missing)}",
        }
    return {
        "ready": True,
        "reason": None,
        "timing_status": "uncertain" if uncertain else "observed",
        "path": list(path),
        "pool": pool,
        "discovery_buyers": evidence["population"],
        "bounds": {
            str(item): list(window) for item, window in bounds.items() if item in path
        },
        "pool_statistics": {
            str(item): stats for item, stats in evidence["items"].items()
        },
        "purchase_timing": {
            "version": 1,
            "fold": "train",
            "core_path": list(path),
            "items": _count_purchase_intervals(
                sorted(item for items in pool.values() for item in items),
                path,
                evidence["histories"],
            ),
        },
    }


def build_evidence_payload(
    connection: duckdb.DuckDBPyConnection,
    data: HeroDiscoveryData,
    row: NominatedCoreBuild,
    assets: dict[int, dict[str, object]],
) -> dict[str, object]:
    members = select_core_owners(data, row["items"])
    metrics = _query_path_item_metrics(connection, members)
    eligible, wealth = _query_path_cohort_summary(connection, members)
    folds = {
        "train": len(select_core_owners(data, row["items"], "discovery")),
        "validation": len(select_core_owners(data, row["items"], "validation")),
        "test": 0,
    }
    frozen = row["guide"]
    core = row["path"]["order"]
    pool = frozen["pool"]
    expected = set(frozen["path"]) | {item for items in pool.values() for item in items}
    items = [
        _build_item_evidence_payload(metric, assets, folds)
        for metric in metrics.iter_rows(named=True)
    ]
    if not expected <= {item["item_id"] for item in items}:
        raise ValueError(f"Hero {data.hero} has incomplete purchase evidence")
    return {
        "path_id": row["identity_id"],
        "path_label": " / ".join(row["names"][:2]),
        "signature_item_ids": sorted(core),
        "discovery": build_discovery_record(row),
        "eligible_player_matches": eligible,
        "selection_eligible_player_matches": eligible,
        "fold_eligible_player_matches": folds,
        "median_final_net_worth": wealth,
        "items": items,
        "core_policy": {
            "version": CORE_POLICY_VERSION,
            "backbone_item_ids": core,
            "default_item_ids": core,
            "backbone_matches": eligible,
            "backbone_fold_matches": folds,
            "default_matches": eligible,
            "default_fold_matches": folds,
            "alternatives": [],
            "candidate_audit": [],
            "evaluation": {
                "method": "frozen corrected core validation",
                "validation": row["validation"],
            },
        },
        "tier_policy": {
            "version": TIER_POLICY_VERSION,
            "item_ids_by_tier": pool,
            "source_fold": "discovery",
            "statistics": frozen["pool_statistics"],
        },
        "purchase_timing": frozen["purchase_timing"],
        "sequence_policy": {
            "version": SEQUENCE_POLICY_VERSION,
            "minimum_support": 20,
            "production_model": row["path"].get("method", "pairwise"),
            "component_expanded_default_path": frozen["path"],
            "transitions": [],
            "evaluation": row["order_validation"],
        },
        "automatic_choices": row["automatic_choices"],
        "situational_policy": {
            "version": SITUATIONAL_POLICY_VERSION,
            "threat_vocabulary": sorted(THREAT_CLASSES),
            "branches": [],
            "abstentions": [
                "Automatic choices require corrected evidence from the same purchase state."
            ],
        },
    }
