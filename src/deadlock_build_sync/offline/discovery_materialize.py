"""Freeze a pool and component path from discovery buyers of one exact core."""

from __future__ import annotations

from typing import TYPE_CHECKING

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
from deadlock_build_sync.mechanics import (
    ItemGraph,
    MechanicsError,
    schedule_component_path,
)
from deadlock_build_sync.purchase_planner import plan_purchases

from .discovery_admission import discovery_record
from .discovery_data import HeroData
from .discovery_ownership import ownership
from .discovery_pool import summarize, timing_policy
from .discovery_types import FrozenGuide, Nomination, PoolEvidence
from .production_items import _item_payload, _path_cohort_summary
from .production_sources import _path_item_metrics
from .production_timing import _interval_counts


def members_for(
    data: HeroData, core: list[int], fold: str | None = None
) -> frozenset[tuple[int, int]]:
    columns = tuple(data.items.index(item) for item in core)
    mask = ownership(data.matrix, columns)
    if fold is not None:
        mask &= data.mask(fold)
    else:
        mask &= data.mask("discovery") | data.mask("validation")
    return frozenset(
        actor for actor, included in zip(data.actors, mask, strict=True) if included
    )


def pool_evidence(
    con: duckdb.DuckDBPyConnection, members: frozenset[tuple[int, int]]
) -> PoolEvidence:
    con.register(
        "_discovery_buyers",
        pl.DataFrame({
            "match_id": [actor[0] for actor in members],
            "player_slot": [actor[1] for actor in members],
        }),
    )
    try:
        rows = con.execute("""
            SELECT p.match_id,p.player_slot,p.item_id,p.buy_time,
                   p.own_net_worth_at_buy,p.state_observed_at_s
            FROM purchases p JOIN _discovery_buyers b USING(match_id,player_slot)
            WHERE p.buy_time<=p.duration_s
            QUALIFY row_number() OVER (
                PARTITION BY p.match_id,p.player_slot,p.item_id
                ORDER BY p.buy_time,p.event_order
            )=1
        """).fetchall()
    finally:
        con.unregister("_discovery_buyers")
    return summarize(rows, len(members))


def item_pool(
    graph: ItemGraph, evidence: PoolEvidence, path: tuple[int, ...]
) -> dict[str, list[int]]:
    ranked = sorted(
        (
            item
            for item, stats in evidence["items"].items()
            if item in graph.nodes and item not in path and stats["buyers"] >= 20
        ),
        key=lambda item: (-evidence["items"][item]["buyers"], item),
    )
    return {
        str(tier): sorted(
            [item for item in ranked if graph.require(item).tier == tier][:10],
            key=lambda item: (
                evidence["items"][item]["time_seconds_q25_q50_q75"][1],
                item,
            ),
        )
        for tier in range(1, 5)
    }


def freeze_guide(
    con: duckdb.DuckDBPyConnection, data: HeroData, row: Nomination, graph: ItemGraph
) -> FrozenGuide:
    evidence = pool_evidence(con, members_for(data, row["items"], "discovery"))
    order = tuple(row["path"]["order"])
    if not order:
        return {"ready": False, "reason": "No supported purchase order"}
    priorities, bounds = timing_policy(evidence["items"])
    try:
        path = schedule_component_path(graph, order, priorities)
        plan = plan_purchases(graph, path, tuple(row["items"]), {})
    except (MechanicsError, ValueError) as error:
        return {"ready": False, "reason": str(error)}
    if tuple(step.item_id for step in plan.actions) != path:
        return {
            "ready": False,
            "reason": "Component planner differs from the frozen route",
        }
    if nondecreasing_window_schedule(path, bounds) is None:
        return {
            "ready": False,
            "reason": "Core order conflicts with observed component wealth windows",
        }
    pool = item_pool(graph, evidence, path)
    if any(not items for items in pool.values()):
        return {
            "ready": False,
            "reason": "At least one item tier has fewer than 20 discovery buyers for every option",
        }
    return {
        "ready": True,
        "reason": None,
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
            "items": _interval_counts(
                sorted(item for items in pool.values() for item in items),
                path,
                evidence["histories"],
            ),
        },
    }


def build_payload(
    con: duckdb.DuckDBPyConnection,
    data: HeroData,
    row: Nomination,
    assets: dict[int, dict[str, object]],
) -> dict[str, object]:
    members = members_for(data, row["items"])
    metrics = _path_item_metrics(con, members)
    eligible, wealth = _path_cohort_summary(con, members)
    folds = {
        "train": len(members_for(data, row["items"], "discovery")),
        "validation": len(members_for(data, row["items"], "validation")),
        "test": 0,
    }
    frozen = row["guide"]
    core = row["path"]["order"]
    pool = frozen["pool"]
    expected = set(frozen["path"]) | {item for items in pool.values() for item in items}
    items = [
        _item_payload(metric, assets, folds) for metric in metrics.iter_rows(named=True)
    ]
    if not expected <= {item["item_id"] for item in items}:
        raise ValueError(f"Hero {data.hero} has incomplete purchase evidence")
    return {
        "path_id": row["identity_id"],
        "path_label": " / ".join(row["names"][:2]),
        "signature_item_ids": sorted(core),
        "discovery": discovery_record(row),
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
            "production_model": "pairwise",
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
