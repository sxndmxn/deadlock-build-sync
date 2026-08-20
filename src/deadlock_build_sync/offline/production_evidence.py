from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from functools import partial
from itertools import combinations
from operator import itemgetter
from pathlib import Path
from typing import Any

import duckdb
import polars as pl
from joblib import Parallel, delayed, parallel_config

from deadlock_build_sync.build_evidence import (
    MAX_COMPARATIVE_INTERVAL_WIDTH,
    MAX_SITUATIONAL_BRANCHES,
    MECHANIC_RESPONSE_THREATS,
    SEQUENCE_POLICY_VERSION,
    THREAT_CLASSES,
    nondecreasing_window_schedule,
)
from deadlock_build_sync.mechanics import (
    BASE_INVENTORY_SLOTS,
    MAX_FLEX_SLOTS,
    InventoryState,
    ItemGraph,
    MechanicsError,
    classify_item_threat_responses,
    purchase_item,
    schedule_component_path,
)
from deadlock_build_sync.mechanics_compatibility import (
    asset_mechanics_refs,
    hero_item_affinity_scores,
)

from .api import read_json
from .build_paths import DiscoveredBuildPath, discover_build_paths
from .config import RunPaths, sha256_json
from .core_policy import (
    complete_default_core,
    cross_fitted_dr_contrast,
    select_supported_backbone,
)
from .late_game import _asset_maps, reconstruct_final_inventory

SCHEMA_VERSION = 4
CORE_ITEM_COUNT = 8
CORE_CANDIDATE_LIMIT = 64
TIER_ITEM_COUNT = 10
MINIMUM_CORE_SUPPORT = 20
HERO_EXPORT_WORKERS = 8
METHOD_VERSION = "state-aware-multi-path-v3"
SEQUENCE_MINIMUM_SUPPORT = 20
CORE_ECONOMY_REFERENCE_MINIMUM_BADGE = 81
DEFAULT_BUILD_PATH_LABEL = "Evidence Default"
_STEAM_CDN_HOST_PATTERN = re.compile(
    r"(?<=://)(clan|shared)\.(?:akamai|fastly)\.steamstatic\.com",
    re.IGNORECASE,
)


class UnsupportedBuildPathError(RuntimeError):
    """Raised when a discovered item path cannot produce a supported legal core."""


@dataclass(frozen=True)
class _HeroExportContext:
    paths: RunPaths
    hero_count: int
    components: dict[int, tuple[int, ...]]
    folds_by_match: dict[int, str]
    normal_assets: list[dict[str, Any]]
    item_graph: ItemGraph
    mechanics_assets_by_id: dict[int, dict[str, Any]]
    item_costs: dict[int, int]
    target_core_cost: int


def _patch_guid(value: object) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, (dict, list)):
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
    return "unknown"


def _normalize_patch_content(value: Any) -> Any:
    if isinstance(value, str):
        return _STEAM_CDN_HOST_PATTERN.sub(r"\1.cdn.steamstatic.com", value)
    if isinstance(value, list):
        return [_normalize_patch_content(nested) for nested in value]
    if isinstance(value, dict):
        return {
            str(key): _normalize_patch_content(nested) for key, nested in value.items()
        }
    return value


def _patch_content_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            _normalize_patch_content(value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    ).hexdigest()


def _patch_at(paths: RunPaths, as_of: datetime) -> dict[str, Any]:
    payload = read_json(paths.raw / "patches.json")
    if isinstance(payload, dict):
        payload = payload.get("patches") or payload.get("data")
    if not isinstance(payload, list):
        raise RuntimeError("patch source does not contain a patch list")
    candidates: list[tuple[datetime, dict[str, Any]]] = []
    for row in payload:
        if not isinstance(row, dict) or not isinstance(row.get("pub_date"), str):
            continue
        published = datetime.fromisoformat(row["pub_date"])
        if published <= as_of:
            candidates.append((published, row))
    if not candidates:
        raise RuntimeError("patch source has no entry at the frozen as-of cutoff")
    published, selected = max(candidates, key=itemgetter(0))
    content_sha256 = _patch_content_sha256(selected.get("content"))
    patch = {
        "title": str(selected.get("title") or "Current patch"),
        "start_timestamp": int(published.timestamp()),
        "published_at": str(selected["pub_date"]),
        "source": str(selected.get("source") or "unknown"),
        "guid": _patch_guid(selected.get("guid")),
        "link": str(selected.get("link") or ""),
        "content_sha256": content_sha256,
    }
    patch["identity"] = sha256_json({
        "source": patch["source"],
        "guid": patch["guid"],
        "published_at": patch["published_at"],
        "link": patch["link"],
        "content_sha256": patch["content_sha256"],
    })
    return patch


def _rank_labels_sha256(paths: RunPaths) -> str:
    rows = read_json(paths.raw / "ranks.json")
    labels = {
        int(row["tier"]): str(row["name"]).strip()
        for row in rows
        if isinstance(row, dict)
        and isinstance(row.get("tier"), int)
        and isinstance(row.get("name"), str)
        and row["name"].strip()
    }
    return sha256_json(labels)


def _supported_core_candidate_is_legal(
    candidate: dict[str, Any],
    graph: ItemGraph | None,
    priorities: dict[int, tuple[float, float, int]] | None,
) -> bool:
    if graph is None or priorities is None:
        return True
    try:
        path = _candidate_path(candidate, graph, priorities)
    except (KeyError, MechanicsError):
        return False
    return _candidate_path_is_legal(candidate, path, graph)


def _top_core_candidates(
    inventories: list[tuple[int, ...]],
    item_costs: dict[int, int],
    maximum_cost: int,
    *,
    graph: ItemGraph | None = None,
    priorities: dict[int, tuple[float, float, int]] | None = None,
) -> list[dict[str, Any]]:
    counts: Counter[tuple[int, ...]] = Counter()
    for inventory in inventories:
        distinct = tuple(sorted(set(inventory)))
        if len(distinct) >= CORE_ITEM_COUNT:
            counts.update(combinations(distinct, CORE_ITEM_COUNT))
    ranked = sorted(counts.items(), key=lambda value: (-value[1], value[0]))
    candidates = []
    for item_ids, matches in ranked:
        if matches < MINIMUM_CORE_SUPPORT:
            break
        if (
            sum(item_costs.get(item_id, maximum_cost + 1) for item_id in item_ids)
            > maximum_cost
        ):
            continue
        candidate = {"item_ids": list(item_ids), "joint_matches": matches}
        if not _supported_core_candidate_is_legal(candidate, graph, priorities):
            continue
        candidates.append(candidate)
        if len(candidates) == CORE_CANDIDATE_LIMIT:
            break
    return candidates


def _inventories_for_hero(
    con: duckdb.DuckDBPyConnection,
    hero_id: int,
    components: dict[int, tuple[int, ...]],
) -> dict[tuple[int, int], tuple[int, ...]]:
    cursor = con.execute(
        f"""
        SELECT match_id, player_slot, item_id, buy_time, sold_time
        FROM purchases
        WHERE hero_id = {hero_id}
        ORDER BY match_id, player_slot, buy_time, event_order
        """
    )
    inventories: dict[tuple[int, int], tuple[int, ...]] = {}
    current: tuple[int, int] | None = None
    purchases: list[tuple[int, int, int]] = []
    while rows := cursor.fetchmany(100_000):
        for match_id, player_slot, item_id, buy_time, sold_time in rows:
            identity = int(match_id), int(player_slot)
            if current is not None and identity != current:
                inventories[current] = reconstruct_final_inventory(
                    purchases, components
                )
                purchases = []
            current = identity
            purchases.append((int(item_id), int(buy_time), int(sold_time)))
    if current is not None:
        inventories[current] = reconstruct_final_inventory(purchases, components)
    return inventories


def _early_inventories_for_hero(
    con: duckdb.DuckDBPyConnection,
    hero_id: int,
) -> dict[tuple[int, int], tuple[int, ...]]:
    rows = con.execute(
        """
        SELECT match_id, player_slot, item_id
        FROM first_purchases
        WHERE hero_id = ? AND own_net_worth_at_buy <= 12000
        ORDER BY match_id, player_slot, buy_time, item_id
        """,
        [hero_id],
    ).fetchall()
    result: dict[tuple[int, int], list[int]] = {}
    for match_id, player_slot, item_id in rows:
        result.setdefault((int(match_id), int(player_slot)), []).append(int(item_id))
    return {identity: tuple(item_ids) for identity, item_ids in result.items()}


def _path_item_metrics(
    con: duckdb.DuckDBPyConnection,
    member_ids: frozenset[tuple[int, int]],
) -> pl.DataFrame:
    members = pl.DataFrame({
        "match_id": [identity[0] for identity in member_ids],
        "player_slot": [identity[1] for identity in member_ids],
    })
    con.register("_build_path_members", members)
    try:
        return con.sql(
            f"""
            WITH events AS (
                SELECT p.item_id, count(*) AS purchase_events
                FROM purchases p
                JOIN _build_path_members m USING (match_id, player_slot)
                GROUP BY p.item_id
            ), items AS (
                SELECT
                    p.hero_id, p.item_id, any_value(p.item_name) AS item_name,
                    any_value(p.tier) AS tier, any_value(p.cost) AS cost,
                    any_value(p.slot) AS slot, any_value(p.active) AS active,
                    count(*) AS adopter_matches,
                    sum(p.won::INTEGER) AS wins,
                    avg(p.won::INTEGER) AS raw_outcome_rate,
                    median(p.buy_time) AS median_buy_time_s,
                    quantile_cont(p.buy_time, 0.25) AS buy_time_q25_s,
                    quantile_cont(p.buy_time, 0.75) AS buy_time_q75_s,
                    median(p.own_net_worth_at_buy) AS median_valid_buy_net_worth,
                    quantile_cont(p.own_net_worth_at_buy, 0.25) AS buy_nw_q25,
                    quantile_cont(p.own_net_worth_at_buy, 0.75) AS buy_nw_q75,
                    count(p.own_net_worth_at_buy) / count(*) AS valid_buy_nw_share
                FROM first_purchases p
                JOIN _build_path_members m USING (match_id, player_slot)
                GROUP BY p.hero_id, p.item_id
                HAVING count(*) >= {MINIMUM_CORE_SUPPORT}
            )
            SELECT i.*, e.purchase_events,
                   {len(member_ids)}::BIGINT AS hero_player_matches,
                   i.adopter_matches / {len(member_ids)}::DOUBLE AS adoption_rate
            FROM items i JOIN events e USING (item_id)
            """
        ).pl()
    finally:
        con.unregister("_build_path_members")


def _path_cohort_summary(
    con: duckdb.DuckDBPyConnection,
    member_ids: frozenset[tuple[int, int]],
) -> tuple[int, int]:
    members = pl.DataFrame({
        "match_id": [identity[0] for identity in member_ids],
        "player_slot": [identity[1] for identity in member_ids],
    })
    con.register("_build_path_members", members)
    try:
        row = con.execute(
            """
            SELECT count(*), median(final_net_worth)
            FROM player_matches p
            JOIN _build_path_members m USING (match_id, player_slot)
            """
        ).fetchone()
    finally:
        con.unregister("_build_path_members")
    if row is None or row[1] is None:
        raise RuntimeError("build path has no cohort summary")
    return int(row[0]), int(row[1])


def _path_label(
    con: duckdb.DuckDBPyConnection,
    path: DiscoveredBuildPath,
    assets_by_id: dict[int, dict[str, Any]],
) -> str:
    members = pl.DataFrame({
        "match_id": [identity[0] for identity in path.member_ids],
        "player_slot": [identity[1] for identity in path.member_ids],
    })
    con.register("_build_path_members", members)
    try:
        row = con.execute(
            """
            SELECT imbued_ability_id, count(DISTINCT (match_id, player_slot)) AS players
            FROM purchases p
            JOIN _build_path_members m USING (match_id, player_slot)
            WHERE imbued_ability_id > 0
            GROUP BY imbued_ability_id
            ORDER BY players DESC, imbued_ability_id
            LIMIT 1
            """
        ).fetchone()
    finally:
        con.unregister("_build_path_members")
    if row is not None and int(row[1]) / len(path.member_ids) >= 0.5:
        ability = assets_by_id.get(int(row[0]), {})
        name = ability.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    slots = [
        str(assets_by_id.get(item_id, {}).get("item_slot_type") or "").casefold()
        for item_id in path.signature_item_ids
    ]
    slot = Counter(value for value in slots if value).most_common(1)
    if slot:
        return f"{slot[0][0].title()} Core"
    if path.signature_item_ids:
        item = assets_by_id.get(path.signature_item_ids[0], {})
        name = item.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return DEFAULT_BUILD_PATH_LABEL


def _core_economy_reference(
    con: duckdb.DuckDBPyConnection,
    cohort: dict[str, Any],
) -> dict[str, int | float]:
    minimum_badge = max(
        CORE_ECONOMY_REFERENCE_MINIMUM_BADGE,
        int(cohort["minimum_badge"]),
    )
    maximum_badge = int(cohort["maximum_badge"])
    if minimum_badge > maximum_badge:
        raise RuntimeError("cohort does not include the Oracle I+ economy reference")
    row = con.execute(
        """
        WITH reference_players AS (
            SELECT match_id, player_slot, duration_s, final_net_worth
            FROM player_matches
            WHERE average_badge BETWEEN ? AND ?
        ), final_inventories AS (
            SELECT match_id, player_slot,
                   count(*) FILTER (WHERE sold_time = 0) AS item_count,
                   sum(cost) FILTER (WHERE sold_time = 0) AS inventory_cost
            FROM purchases
            WHERE average_badge BETWEEN ? AND ?
            GROUP BY match_id, player_slot
        ), observed AS (
            SELECT players.match_id, players.player_slot, players.duration_s,
                   players.final_net_worth,
                   coalesce(inventory.item_count, 0) AS item_count,
                   coalesce(inventory.inventory_cost, 0) AS inventory_cost
            FROM reference_players AS players
            LEFT JOIN final_inventories AS inventory
              USING (match_id, player_slot)
        )
        SELECT count(DISTINCT match_id), count(*), avg(duration_s),
               median(duration_s), avg(final_net_worth), median(final_net_worth),
               median(item_count), median(inventory_cost)
        FROM observed
        """,
        [minimum_badge, maximum_badge, minimum_badge, maximum_badge],
    ).fetchone()
    if row is None or row[6] is None or row[7] is None or int(row[6]) <= 0:
        raise RuntimeError("Oracle I+ economy reference is empty")
    median_inventory_items = int(row[6])
    median_inventory_cost = int(row[7])
    reserved_item_equivalents = min(MAX_FLEX_SLOTS, median_inventory_items - 1)
    target_cost = round(
        median_inventory_cost
        * (median_inventory_items - reserved_item_equivalents)
        / median_inventory_items
    )
    return {
        "minimum_badge": minimum_badge,
        "maximum_badge": maximum_badge,
        "matches": int(row[0]),
        "player_matches": int(row[1]),
        "mean_duration_s": float(row[2]),
        "median_duration_s": float(row[3]),
        "mean_final_net_worth": float(row[4]),
        "median_final_net_worth": float(row[5]),
        "median_final_inventory_items": median_inventory_items,
        "median_final_inventory_cost": median_inventory_cost,
        "reserved_situational_item_equivalents": reserved_item_equivalents,
        "target_core_cost": target_cost,
    }


def _optional_float(value: float | None) -> float | None:
    return float(value) if value is not None else None


def _item_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "item_id": int(row["item_id"]),
        "item": str(row["item_name"]),
        "tier": int(row["tier"]),
        "cost": int(row["cost"]),
        "slot": str(row["slot"]),
        "active": bool(row["active"]),
        "adopter_matches": int(row["adopter_matches"]),
        "eligible_player_matches": int(row["hero_player_matches"]),
        "purchase_events": int(row["purchase_events"]),
        "wins": int(row["wins"]),
        "adoption": float(row["adoption_rate"]),
        "observed_outcome_rate": float(row["raw_outcome_rate"]),
        "median_buy_time_s": float(row["median_buy_time_s"]),
        "median_valid_buy_net_worth": _optional_float(
            row["median_valid_buy_net_worth"]
        ),
        "buy_net_worth_q25": _optional_float(row["buy_nw_q25"]),
        "buy_net_worth_q75": _optional_float(row["buy_nw_q75"]),
        "valid_buy_net_worth_share": float(row["valid_buy_nw_share"]),
    }


def _purchase_priorities(
    hero_metrics: pl.DataFrame,
) -> dict[int, tuple[float, float, int]]:
    return {
        item_id: (
            float(row.get("median_valid_buy_net_worth") or float("inf")),
            float(row.get("median_buy_time_s") or float("inf")),
            item_id,
        )
        for row in hero_metrics.iter_rows(named=True)
        for item_id in (int(row["item_id"]),)
    }


def _purchase_window_bounds(
    hero_metrics: pl.DataFrame,
) -> dict[int, tuple[float, float]]:
    result: dict[int, tuple[float, float]] = {}
    for row in hero_metrics.iter_rows(named=True):
        lower = row.get("buy_nw_q25")
        upper = row.get("buy_nw_q75")
        if lower is not None and upper is not None:
            result[int(row["item_id"])] = (float(lower), float(upper))
    return result


def _complete_priorities(
    priorities: dict[int, tuple[float, float, int]],
    graph: ItemGraph,
) -> dict[int, tuple[float, float, int]]:
    return {
        item_id: priorities.get(item_id, (float("inf"), float("inf"), item_id))
        for item_id in graph.nodes
    }


def _candidate_path(
    candidate: dict[str, Any],
    graph: ItemGraph,
    priorities: dict[int, tuple[float, float, int]],
) -> tuple[int, ...]:
    core = sorted(
        (int(item_id) for item_id in candidate["item_ids"]),
        key=lambda item_id: priorities[item_id],
    )
    return schedule_component_path(graph, core, priorities)


def _candidate_path_is_legal(
    candidate: dict[str, Any],
    path: tuple[int, ...],
    graph: ItemGraph,
) -> bool:
    if len(path) != len(set(path)):
        return False
    state = InventoryState()
    try:
        for item_id in path:
            state = purchase_item(graph, state, item_id)
    except MechanicsError:
        return False
    return set(state.owned) == {int(item_id) for item_id in candidate["item_ids"]}


def _ranked_agreement_orders(
    item_ids: tuple[int, ...],
    precedence: Counter[tuple[int, int]],
) -> list[tuple[int, tuple[int, ...]]]:
    ordered_items = tuple(sorted(item_ids))
    states: dict[int, dict[tuple[int, ...], int]] = {0: {(): 0}}
    full_mask = (1 << len(ordered_items)) - 1
    for mask in range(full_mask + 1):
        current = states.get(mask)
        if current is None:
            continue
        for index, item_id in enumerate(ordered_items):
            bit = 1 << index
            if mask & bit:
                continue
            added = sum(
                precedence[prior_id, item_id]
                for prior_index, prior_id in enumerate(ordered_items)
                if mask & (1 << prior_index)
            )
            target_mask = mask | bit
            target = states.setdefault(target_mask, {})
            for path, score in current.items():
                next_path = (*path, item_id)
                target[next_path] = score + added
    return sorted(
        ((score, path) for path, score in states[full_mask].items()),
        key=lambda value: (-value[0], value[1]),
    )


def _maximum_agreement_orders(
    item_ids: tuple[int, ...],
    precedence: Counter[tuple[int, int]],
) -> tuple[tuple[int, ...], tuple[int, ...], int, int]:
    """Return the best and runner-up target orders under pairwise agreement."""
    ranked = _ranked_agreement_orders(item_ids, precedence)
    best_score, best = ranked[0]
    runner_score, runner = ranked[1] if len(ranked) > 1 else ranked[0]
    return best, runner, best_score, runner_score


def _observed_purchase_precedence(
    rows: list[tuple[Any, ...]],
    supporting_players: set[tuple[int, int]],
    item_ids: tuple[int, ...],
) -> Counter[tuple[int, int]]:
    observations: dict[tuple[int, int], dict[int, float]] = {}
    for match_id, player_slot, item_id, buy_time in rows:
        identity = int(match_id), int(player_slot)
        if identity in supporting_players:
            observations.setdefault(identity, {})[int(item_id)] = float(buy_time)
    precedence: Counter[tuple[int, int]] = Counter()
    for times in observations.values():
        for first, second in combinations(item_ids, 2):
            if (
                first not in times
                or second not in times
                or times[first] == times[second]
            ):
                continue
            before, after = (
                (first, second) if times[first] < times[second] else (second, first)
            )
            precedence[before, after] += 1
    return precedence


def _feasible_core_orders(
    candidate: dict[str, Any],
    item_ids: tuple[int, ...],
    precedence: Counter[tuple[int, int]],
    graph: ItemGraph,
    priorities: dict[int, tuple[float, float, int]],
    window_bounds: dict[int, tuple[float, float]],
) -> list[tuple[int, tuple[int, ...], tuple[int, ...], tuple[float, ...]]]:
    legal_orders = []
    for score, order in _ranked_agreement_orders(item_ids, precedence):
        try:
            path = schedule_component_path(graph, order, priorities)
        except MechanicsError:
            continue
        window_schedule = nondecreasing_window_schedule(path, window_bounds)
        if not _candidate_path_is_legal(candidate, path, graph):
            continue
        if window_schedule is None:
            continue
        legal_orders.append((score, order, path, window_schedule))
        if len(legal_orders) == 2:
            break
    return legal_orders


def _core_target_order(
    con: duckdb.DuckDBPyConnection,
    hero_id: int,
    candidate: dict[str, Any],
    supporting_players: set[tuple[int, int]],
    graph: ItemGraph,
    priorities: dict[int, tuple[float, float, int]],
    window_bounds: dict[int, tuple[float, float]],
) -> tuple[tuple[int, ...], dict[str, Any]]:
    item_ids = tuple(int(item_id) for item_id in candidate["item_ids"])
    placeholders = ", ".join("?" for _ in item_ids)
    rows = con.execute(
        f"""
        SELECT match_id, player_slot, item_id, min(buy_time) AS buy_time
        FROM first_purchases
        WHERE hero_id = ? AND item_id IN ({placeholders})
        GROUP BY match_id, player_slot, item_id
        ORDER BY match_id, player_slot, buy_time
        """,
        [hero_id, *item_ids],
    ).fetchall()
    precedence = _observed_purchase_precedence(rows, supporting_players, item_ids)
    legal_orders = _feasible_core_orders(
        candidate, item_ids, precedence, graph, priorities, window_bounds
    )
    if not legal_orders:
        raise RuntimeError(
            f"hero {hero_id} core has no mechanics- and soul-window-feasible "
            "target order"
        )
    best_score, best, best_path, best_window_schedule = legal_orders[0]
    runner_score, runner, _, _ = (
        legal_orders[1] if len(legal_orders) > 1 else legal_orders[0]
    )
    common_prefix = next(
        (
            index
            for index, (left, right) in enumerate(zip(best, runner, strict=True))
            if left != right
        ),
        len(best),
    )
    return best, {
        "method": "window_constrained_pairwise_target_precedence_subset_dp",
        "window_constraint": "nondecreasing_first_ownership_iqr",
        "window_schedule": [
            {"item_id": item_id, "minimum_feasible_net_worth": checkpoint}
            for item_id, checkpoint in zip(best_path, best_window_schedule, strict=True)
        ],
        "target_order": list(best),
        "agreement_support": best_score,
        "runner_up_order": list(runner),
        "runner_up_support": runner_score,
        "near_variant": (
            best_score > 0 and runner_score >= 0.9 * best_score and common_prefix <= 5
        ),
    }


def _duplicate_free_core_candidates(
    core_candidates: list[dict[str, Any]],
    hero_metrics: pl.DataFrame,
    graph: ItemGraph,
) -> list[dict[str, Any]]:
    priorities = _purchase_priorities(hero_metrics)
    result = []
    for candidate in core_candidates:
        try:
            path = _candidate_path(candidate, graph, priorities)
        except MechanicsError:
            continue
        if _candidate_path_is_legal(candidate, path, graph):
            result.append(candidate)
    return result


def _expanded_default_path(
    core_candidates: list[dict[str, Any]],
    hero_metrics: pl.DataFrame,
    graph: ItemGraph,
    target_order: tuple[int, ...] | None = None,
) -> list[int]:
    if not core_candidates:
        raise RuntimeError("hero has no supported duplicate-free eight-item core")
    priorities = _complete_priorities(_purchase_priorities(hero_metrics), graph)
    if target_order is None:
        path = _candidate_path(core_candidates[0], graph, priorities)
    else:
        path = schedule_component_path(graph, target_order, priorities)
    if not _candidate_path_is_legal(core_candidates[0], path, graph):
        raise RuntimeError("component-expanded default path is not a legal final core")
    return list(path)


def _sequence_rows(
    con: duckdb.DuckDBPyConnection,
    hero_id: int,
    member_ids: frozenset[tuple[int, int]] | None = None,
) -> list[dict[str, Any]]:
    join = ""
    if member_ids is not None:
        members = pl.DataFrame({
            "match_id": [identity[0] for identity in member_ids],
            "player_slot": [identity[1] for identity in member_ids],
        })
        con.register("_sequence_path_members", members)
        join = "JOIN _sequence_path_members m USING (match_id, player_slot)"
    try:
        rows = con.execute(
            f"""
        WITH timestamped AS (
            SELECT p.*, count(*) OVER (
                PARTITION BY p.match_id, p.player_slot, p.buy_time
            ) AS bucket_size
            FROM first_purchases p
            {join}
            WHERE p.fold = 'train' AND p.hero_id = ?
        ), numbered AS (
            SELECT match_id, player_slot, item_id,
                   row_number() OVER (
                       PARTITION BY match_id, player_slot ORDER BY buy_time
                   ) - 1 AS position,
                   lag(item_id, 1, 0) OVER (
                       PARTITION BY match_id, player_slot ORDER BY buy_time
                   ) AS previous_item_id,
                   first_value(item_id) OVER (
                       PARTITION BY match_id, player_slot ORDER BY buy_time
                   ) AS observed_first_item_id
            FROM timestamped
            WHERE bucket_size = 1
        )
        SELECT CASE WHEN position = 0 THEN 0 ELSE observed_first_item_id END,
               previous_item_id, position, item_id
        FROM numbered
        ORDER BY match_id, player_slot, position
        """,
            [hero_id],
        ).fetchall()
    finally:
        if member_ids is not None:
            con.unregister("_sequence_path_members")
    events = [tuple(int(value) for value in row) for row in rows]
    specifications = (
        ("first_previous_position", (0, 1, 2)),
        ("previous_position", (1, 2)),
        ("position", (2,)),
        ("popularity", ()),
    )
    output: list[dict[str, Any]] = []
    for level, indices in specifications:
        counts: Counter[tuple[tuple[int, ...], int]] = Counter()
        contexts: Counter[tuple[int, ...]] = Counter()
        for first_item, previous_item, position, next_item in events:
            values = (first_item, previous_item, position)
            context = tuple(values[index] for index in indices)
            counts[context, next_item] += 1
            contexts[context] += 1
        for (context, next_item), support in sorted(
            counts.items(),
            key=lambda value: (value[0][0], -value[1], value[0][1]),
        ):
            if support < SEQUENCE_MINIMUM_SUPPORT:
                continue
            context_values = dict(zip(indices, context, strict=True))
            output.append({
                "level": level,
                "first_item_id": context_values.get(0, 0),
                "previous_item_id": context_values.get(1, 0),
                "position": context_values.get(2, 0),
                "next_item_id": next_item,
                "support": support,
                "context_support": contexts[context],
            })
    if not output:
        raise RuntimeError(f"hero {hero_id} has no supported sequence transitions")
    return output


def _sequence_evaluation(paths: RunPaths, hero_id: int) -> list[dict[str, Any]]:
    path = paths.tables / "sequence_model_evaluation.csv"
    if not path.is_file():
        return []
    frame = pl.read_csv(path).filter(pl.col("hero_id") == hero_id)
    return frame.to_dicts()


type _QualifiedSituationalBranch = tuple[
    tuple[float, ...],
    dict[str, Any],
    dict[str, Any],
]
type _SituationalEvidence = tuple[
    pl.DataFrame,
    dict[int, dict[str, Any]],
    dict[str, dict[str, Any]],
]


def _load_situational_evidence(
    paths: RunPaths,
    hero_id: int,
) -> _SituationalEvidence | None:
    matchup_path = paths.tables / "matchup_interactions.csv"
    overlap_path = paths.tables / "state_overlap_diagnostics.csv"
    stability_path = paths.tables / "matchup_temporal_stability.csv"
    if not (
        matchup_path.is_file() and overlap_path.is_file() and stability_path.is_file()
    ):
        return None
    matchups = pl.read_csv(matchup_path).filter(pl.col("hero_id") == hero_id)
    overlap = pl.read_csv(overlap_path).filter(pl.col("hero_id") == hero_id)
    stability = pl.read_csv(stability_path).filter(pl.col("hero_id") == hero_id)
    overlap_by_item = {
        int(row["item_id"]): row for row in overlap.iter_rows(named=True)
    }
    stability_by_scope = {
        str(row["scope"]): row for row in stability.iter_rows(named=True)
    }
    return matchups, overlap_by_item, stability_by_scope


def _bounded_comparative_interval(
    row: dict[str, Any],
) -> tuple[float, float] | None:
    interval_low = row.get("comparative_interval_low")
    interval_high = row.get("comparative_interval_high")
    bounded = (
        isinstance(interval_low, (int, float))
        and isinstance(interval_high, (int, float))
        and math.isfinite(float(interval_low))
        and math.isfinite(float(interval_high))
        and float(interval_low) <= float(interval_high)
        and float(interval_high) - float(interval_low) <= MAX_COMPARATIVE_INTERVAL_WIDTH
    )
    if not bounded:
        return None
    return float(interval_low), float(interval_high)


def _evaluate_situational_response(
    row: dict[str, Any],
    response: str,
    diagnostic: dict[str, Any],
    temporal: dict[str, Any],
) -> tuple[dict[str, Any], _QualifiedSituationalBranch | None]:
    item_id = int(row["item_id"])
    effective = float(diagnostic.get("effective_support") or 0.0)
    state_coverage = float(diagnostic.get("state_coverage") or 0.0)
    comparator_item_id = int(row.get("comparator_item_id") or 0)
    comparison_support = int(row.get("comparison_support") or 0)
    comparative_interval = _bounded_comparative_interval(row)
    stable = (
        float(temporal.get("spearman") or 0.0) >= 0.3
        and float(temporal.get("sign_agreement") or 0.0) >= 0.6
    )
    gates = {
        "mechanics": True,
        "same_opportunity": bool(row.get("same_opportunity")),
        "comparator": comparator_item_id > 0,
        "support": int(row["observations"]) >= 20,
        "comparison_support": comparison_support >= 20,
        "effective_support": effective >= 20,
        "overlap": state_coverage >= 0.5,
        "chronological_stability": stable,
        "bounded_comparative_uncertainty": comparative_interval is not None,
        "comparative_advantage": (
            comparative_interval is not None and comparative_interval[0] > 0
        ),
    }
    passed = all(gates.values())
    threat = MECHANIC_RESPONSE_THREATS[response]
    enemy_id = int(row["enemy_hero_id"])
    comparator = (
        f"same-opportunity item {comparator_item_id} or save"
        if comparator_item_id
        else "unavailable"
    )
    candidate = {
        "threat": threat,
        "item_id": item_id,
        "comparator_item_id": comparator_item_id or None,
        "enemy_hero_id": enemy_id,
        "scope": str(row["scope"]),
        "mechanic_ref": f"item/{item_id}/{response}",
        "comparator": comparator,
        "support": int(row["observations"]),
        "comparison_support": comparison_support,
        "effective_support": effective,
        "overlap": state_coverage,
        "stable": stable,
        "comparative_interval": [
            row.get("comparative_interval_low"),
            row.get("comparative_interval_high"),
        ],
        "gates": gates,
        "qualified": passed,
        "admitted": False,
    }
    if not passed or comparative_interval is None:
        return candidate, None
    branch = {
        "threat": threat,
        "item_id": item_id,
        "enemy_hero_id": enemy_id,
        "mechanic_ref": f"item/{item_id}/{response}",
        "comparator": comparator,
        "comparator_item_id": comparator_item_id,
        "comparison_support": comparison_support,
        "same_opportunity": True,
        "support": int(row["observations"]),
        "effective_support": effective,
        "overlap": state_coverage,
        "stable": stable,
        "comparative_interval": list(comparative_interval),
        "trigger": (
            f"Enemy hero {enemy_id} presents material {threat.replace('_', ' ')}."
        ),
        "replacement": (
            f"Choose item {item_id} instead of item {comparator_item_id} "
            "at the matched opportunity."
        ),
        "execution": (
            f"Use the verified {response.replace('_', ' ')} mechanic while the "
            "trigger remains observable."
        ),
        "failure_condition": (
            "Skip when the threat is not material or the compared decision state "
            "no longer matches."
        ),
    }
    score = (
        float(str(row["scope"]) == "same_lane"),
        state_coverage,
        effective,
        float(row["observations"]),
        -float(item_id),
    )
    return candidate, (score, candidate, branch)


def _collect_situational_candidates(
    evidence: _SituationalEvidence,
    assets: list[dict[str, Any]],
    excluded_item_ids: frozenset[int],
    eligible_item_ids: frozenset[int] | None,
) -> tuple[list[dict[str, Any]], list[_QualifiedSituationalBranch]]:
    matchups, overlap_by_item, stability_by_scope = evidence
    asset_by_id = {
        int(asset["id"]): asset for asset in assets if isinstance(asset.get("id"), int)
    }
    candidates: list[dict[str, Any]] = []
    qualified: list[_QualifiedSituationalBranch] = []
    for row in matchups.iter_rows(named=True):
        item_id = int(row["item_id"])
        comparator_item_id = int(row.get("comparator_item_id") or 0)
        if item_id in excluded_item_ids or (
            eligible_item_ids is not None
            and (
                item_id not in eligible_item_ids
                or comparator_item_id not in eligible_item_ids
            )
        ):
            continue
        asset = asset_by_id.get(item_id)
        if asset is None:
            continue
        diagnostic = overlap_by_item.get(item_id, {})
        temporal = stability_by_scope.get(str(row["scope"]), {})
        for response in sorted(classify_item_threat_responses(asset)):
            candidate, branch = _evaluate_situational_response(
                row, response, diagnostic, temporal
            )
            candidates.append(candidate)
            if branch is not None:
                qualified.append(branch)
    return candidates, qualified


def _admit_situational_branches(
    qualified: list[_QualifiedSituationalBranch],
) -> list[dict[str, Any]]:
    ordered = sorted(
        qualified,
        key=lambda row: (
            tuple(-value for value in row[0]),
            str(row[2]["threat"]),
            int(row[2]["enemy_hero_id"]),
            int(row[2]["item_id"]),
        ),
    )
    branches: list[dict[str, Any]] = []
    used_items: set[int] = set()
    used_guards: set[tuple[str, int]] = set()
    for _, candidate, branch in ordered:
        item_id = int(branch["item_id"])
        guard = (str(branch["threat"]), int(branch["enemy_hero_id"]))
        if item_id in used_items or guard in used_guards:
            continue
        candidate["admitted"] = True
        branches.append(branch)
        used_items.add(item_id)
        used_guards.add(guard)
        if len(branches) == MAX_SITUATIONAL_BRANCHES:
            break
    return branches


def _situational_abstentions(
    candidate_count: int,
    branch_count: int,
) -> list[str]:
    rejected = candidate_count - branch_count
    if rejected:
        return [
            (
                f"{rejected} mechanics-backed candidate(s) failed at least one "
                "same-opportunity, comparator, support, overlap, bounded-uncertainty, "
                "or chronological-stability gate."
            )
        ]
    if not branch_count:
        return ["No mechanics-backed situational candidate was available."]
    return []


def _situational_policy(
    paths: RunPaths,
    hero_id: int,
    assets: list[dict[str, Any]],
    *,
    excluded_item_ids: frozenset[int] = frozenset(),
    eligible_item_ids: frozenset[int] | None = None,
) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    qualified: list[_QualifiedSituationalBranch] = []
    evidence = _load_situational_evidence(paths, hero_id)
    if evidence is not None:
        candidates, qualified = _collect_situational_candidates(
            evidence, assets, excluded_item_ids, eligible_item_ids
        )
    branches = _admit_situational_branches(qualified)
    return {
        "version": 1,
        "threat_vocabulary": sorted(THREAT_CLASSES),
        "branches": branches,
        "candidate_audit": candidates,
        "abstentions": _situational_abstentions(len(candidates), len(branches)),
    }


def _atomic_write(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = (
        json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode()
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
        temporary = None
        descriptor = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _folds_by_match(con: duckdb.DuckDBPyConnection) -> dict[int, str]:
    return {
        int(match_id): str(fold)
        for match_id, fold in con.execute(
            "SELECT match_id, fold FROM match_folds"
        ).fetchall()
    }


def _core_decisions(con: duckdb.DuckDBPyConnection, hero_id: int) -> pl.DataFrame:
    arrow = con.execute(
        """
        SELECT match_id, player_slot, fold, item_id, won, average_badge,
               phase, buy_time, own_net_worth_at_buy, state_observed_at_s,
               own_team_net_worth, enemy_team_net_worth, team_net_worth_lead,
               state_age_s, prior_catalog_spend, prior_purchase_count
        FROM decision_opportunities
        WHERE hero_id = ?
        """,
        [hero_id],
    ).fetch_arrow_table()
    frame = pl.from_arrow(arrow)
    if not isinstance(frame, pl.DataFrame):
        raise RuntimeError("decision query did not return a table")
    return frame


def _replacement_is_legal(
    default_item_ids: tuple[int, ...],
    comparator_item_id: int,
    alternative_item_id: int,
    graph: ItemGraph,
    priorities: dict[int, tuple[float, float, int]],
) -> bool:
    replacement = tuple(
        alternative_item_id if item_id == comparator_item_id else item_id
        for item_id in default_item_ids
    )
    if len(set(replacement)) != len(default_item_ids):
        return False
    candidate = {"item_ids": list(replacement)}
    try:
        path = schedule_component_path(graph, replacement, priorities)
    except MechanicsError:
        return False
    return _candidate_path_is_legal(candidate, path, graph)


def _core_alternative_candidates(
    metrics: dict[int, dict[str, Any]],
    default_item_ids: tuple[int, ...],
    default_set: set[int],
    comparator_id: int,
    comparator: dict[str, Any],
    graph: ItemGraph,
    priorities: dict[int, tuple[float, float, int]],
) -> list[dict[str, Any]]:
    candidates = (
        row
        for item_id, row in metrics.items()
        if item_id not in default_set
        and int(row["tier"]) == int(comparator["tier"])
        and int(row["adopter_matches"]) >= MINIMUM_CORE_SUPPORT
        and _replacement_is_legal(
            default_item_ids,
            comparator_id,
            item_id,
            graph,
            priorities,
        )
    )
    return sorted(
        candidates,
        key=lambda row: (-int(row["adopter_matches"]), int(row["item_id"])),
    )[:2]


def _best_core_alternatives_by_item(
    alternatives: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    best_by_item: dict[int, dict[str, Any]] = {}
    rankings: dict[int, tuple[float, float, int]] = {}
    for row in alternatives:
        item_id = int(row["item_id"])
        ranking = (
            float(row["effective_support"]),
            -(
                float(row["comparative_interval"][1])
                - float(row["comparative_interval"][0])
            ),
            -int(row["stage"]),
        )
        if item_id not in rankings or ranking > rankings[item_id]:
            best_by_item[item_id] = row
            rankings[item_id] = ranking
    return sorted(
        best_by_item.values(),
        key=lambda row: (int(row["stage"]), int(row["item_id"])),
    )


def _core_alternatives(
    con: duckdb.DuckDBPyConnection,
    hero_id: int,
    default_item_ids: tuple[int, ...],
    backbone_item_ids: tuple[int, ...],
    hero_metrics: pl.DataFrame,
    item_assets: dict[int, dict[str, Any]],
    graph: ItemGraph,
    priorities: dict[int, tuple[float, float, int]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    decisions = _core_decisions(con, hero_id)
    metrics = {int(row["item_id"]): row for row in hero_metrics.iter_rows(named=True)}
    default_set = set(default_item_ids)
    backbone_set = set(backbone_item_ids)
    alternatives: list[dict[str, Any]] = []
    audit: list[dict[str, Any]] = []
    for stage, comparator_id in enumerate(default_item_ids, start=1):
        if comparator_id in backbone_set:
            continue
        comparator = metrics[comparator_id]
        candidates = _core_alternative_candidates(
            metrics,
            default_item_ids,
            default_set,
            comparator_id,
            comparator,
            graph,
            priorities,
        )
        for candidate in candidates:
            item_id = int(candidate["item_id"])
            try:
                contrast = cross_fitted_dr_contrast(decisions, item_id, comparator_id)
            except (RuntimeError, ValueError) as error:
                audit.append({
                    "item_id": item_id,
                    "comparator_item_id": comparator_id,
                    "stage": stage,
                    "admitted": False,
                    "failed_gates": ["estimability"],
                    "reason": str(error),
                })
                continue
            record = {
                "item_id": item_id,
                "comparator_item_id": comparator_id,
                "stage": stage,
                "support": contrast.support,
                "comparison_support": contrast.comparison_support,
                "effective_support": contrast.effective_support,
                "overlap": contrast.overlap,
                "maximum_weight": contrast.maximum_weight,
                "maximum_standardized_mean_difference": (
                    contrast.maximum_standardized_mean_difference
                ),
                "dr_estimate": contrast.estimate,
                "comparative_interval": list(contrast.interval),
                "fold_estimates": contrast.fold_estimates,
                "clipped_sensitivity": contrast.clipped_sensitivity,
                "stable": contrast.stable,
                "admitted": contrast.admitted,
                "failed_gates": list(contrast.failed_gates),
            }
            audit.append(record)
            if not contrast.admitted:
                continue
            item_name = str(candidate["item_name"])
            comparator_name = str(comparator["item_name"])
            refs = asset_mechanics_refs(item_assets[item_id])
            alternatives.append({
                **record,
                "trigger": (
                    f"Choose {item_name} over {comparator_name} only when its "
                    "documented mechanic fits the current fight."
                ),
                "execution": (
                    f"Replace {comparator_name} at default stage {stage}; keep the "
                    "remaining automatic path unchanged."
                ),
                "failure_condition": (
                    f"Stay on {comparator_name} when that observable need is absent "
                    "or the replacement would delay the next supported purchase."
                ),
                "mechanics_refs": list(refs),
            })
    admitted = _best_core_alternatives_by_item(alternatives)
    return admitted[:10], audit


def _parallel_hero_export(
    jobs: list[tuple[int, dict[str, Any]]],
    worker: Callable[[tuple[int, dict[str, Any]]], dict[str, Any]],
) -> list[dict[str, Any]]:
    worker_count = min(HERO_EXPORT_WORKERS, len(jobs))
    with parallel_config(
        backend="loky",
        n_jobs=worker_count,
        inner_max_num_threads=1,
    ):
        return Parallel()(delayed(worker)(job) for job in jobs)


def _resolved_path_label(
    raw_label: str,
    path: DiscoveredBuildPath,
    label_counts: Counter[str],
    assets_by_id: dict[int, dict[str, Any]],
) -> str:
    if label_counts[raw_label] <= 1 or not path.signature_item_ids:
        return raw_label
    asset = assets_by_id.get(path.signature_item_ids[0], {})
    item_name = asset.get("name")
    if isinstance(item_name, str) and item_name.strip():
        return f"{raw_label} / {item_name.strip()}"
    return raw_label


def _supported_route_members(
    inventories: dict[tuple[int, int], tuple[int, ...]],
    item_ids: tuple[int, ...],
) -> set[tuple[int, int]]:
    required = set(item_ids)
    return {
        identity
        for identity, inventory in inventories.items()
        if required <= set(inventory)
    }


def _core_evaluation_contract() -> dict[str, Any]:
    return {
        "chronological_split": "60/20/20 by match start",
        "cross_fitting": "five match-group folds within each chronological fold",
        "estimand": "pairwise like-state win-probability contrast at a logged purchase opportunity",
        "target_trial": {
            "eligibility": "first unambiguous purchase in a hero/phase/tier decision stratum",
            "time_zero": "last telemetry state observed no later than the purchase",
            "candidate_slate": "same-tier catalog items plus save",
            "treatments": "admitted item versus default comparator; save remains in the logged slate",
            "assignment_model": "cross-fitted behavior propensity from pre-decision state",
            "follow_up": "through match completion",
            "outcome": "team win indicator",
            "censoring": "no post-decision state is used; unobserved save choices are not estimated",
            "estimand": "observational pairwise average win-probability contrast over overlap states",
        },
        "support_floor": 20,
        "effective_support_floor": 20,
        "overlap_floor": 0.5,
        "maximum_standardized_mean_difference": 0.1,
        "maximum_interval_width": 0.1,
        "weight_clips": [5, 10, 20],
        "outcome_claim": "assumption-dependent; not proof of causation",
    }


def _build_path_payload(
    con: duckdb.DuckDBPyConnection,
    hero_id: int,
    hero: dict[str, Any],
    path: DiscoveredBuildPath,
    raw_label: str,
    label_counts: Counter[str],
    inventories: dict[tuple[int, int], tuple[int, ...]],
    context: _HeroExportContext,
) -> dict[str, Any]:
    path_inventories = {identity: inventories[identity] for identity in path.member_ids}
    path_metrics = _path_item_metrics(con, path.member_ids)
    eligible_item_ids = frozenset(
        int(item_id) for item_id in path_metrics["item_id"].to_list()
    )
    eligible_matches, median_final_net_worth = _path_cohort_summary(
        con, path.member_ids
    )
    priorities = _complete_priorities(
        _purchase_priorities(path_metrics), context.item_graph
    )
    window_bounds = _purchase_window_bounds(path_metrics)
    try:
        backbone = select_supported_backbone(
            path_inventories,
            context.folds_by_match,
            context.item_graph,
            mechanic_affinity=hero_item_affinity_scores(hero, context.normal_assets),
        )
        default_item_ids, default_matches, completion_audit = complete_default_core(
            backbone,
            path_inventories,
            context.folds_by_match,
            context.item_graph,
            context.item_costs,
            median_final_net_worth,
            target_cost=context.target_core_cost,
        )
    except RuntimeError as error:
        raise UnsupportedBuildPathError(str(error)) from error
    state_candidate = {
        "item_ids": list(default_item_ids),
        "joint_matches": default_matches,
    }
    core_candidates = _top_core_candidates(
        list(path_inventories.values()),
        context.item_costs,
        median_final_net_worth,
        graph=context.item_graph,
        priorities=priorities,
    )
    if not core_candidates:
        raise UnsupportedBuildPathError(
            f"hero {hero_id} path {path.path_id} has no supported legal core"
        )
    target_order, route_diagnostics = _core_target_order(
        con,
        hero_id,
        state_candidate,
        _supported_route_members(path_inventories, default_item_ids),
        context.item_graph,
        priorities,
        window_bounds,
    )
    alternatives, alternative_audit = _core_alternatives(
        con,
        hero_id,
        target_order,
        backbone.item_ids,
        path_metrics,
        context.mechanics_assets_by_id,
        context.item_graph,
        priorities,
    )
    return {
        "path_id": path.path_id,
        "path_label": _resolved_path_label(
            raw_label,
            path,
            label_counts,
            context.mechanics_assets_by_id,
        ),
        "signature_item_ids": list(path.signature_item_ids),
        "discovery": path.diagnostics,
        "eligible_player_matches": eligible_matches,
        "median_final_net_worth": median_final_net_worth,
        "core_candidates": core_candidates,
        "core_policy": {
            "version": 1,
            "backbone_item_ids": list(backbone.item_ids),
            "default_item_ids": list(target_order),
            "backbone_matches": backbone.matches,
            "backbone_fold_matches": backbone.fold_matches,
            "default_matches": default_matches,
            "alternatives": alternatives,
            "candidate_audit": [
                *backbone.audit,
                *completion_audit,
                *alternative_audit,
            ],
            "evaluation": _core_evaluation_contract(),
        },
        "items": [
            _item_payload(row)
            for row in path_metrics.sort("item_id").iter_rows(named=True)
        ],
        "sequence_policy": {
            "version": SEQUENCE_POLICY_VERSION,
            "minimum_support": SEQUENCE_MINIMUM_SUPPORT,
            "production_model": "deterministic_backoff",
            "component_expanded_default_path": _expanded_default_path(
                [state_candidate],
                path_metrics,
                context.item_graph,
                target_order,
            ),
            "route_diagnostics": route_diagnostics,
            "transitions": _sequence_rows(con, hero_id, path.member_ids),
            "evaluation": {
                "chronological_fold": "test",
                "metrics": _sequence_evaluation(context.paths, hero_id),
                "claim": "outcome-agnostic next-action imitation",
            },
        },
        "situational_policy": _situational_policy(
            context.paths,
            hero_id,
            context.normal_assets,
            excluded_item_ids=frozenset(default_item_ids),
            eligible_item_ids=eligible_item_ids,
        ),
    }


def _fallback_build_path(
    inventories: dict[tuple[int, int], tuple[int, ...]],
    folds_by_match: dict[int, str],
) -> DiscoveredBuildPath:
    members = frozenset(inventories)
    return DiscoveredBuildPath(
        "default",
        members,
        (),
        dict(Counter(folds_by_match[identity[0]] for identity in members)),
        {
            "selection": "single-supported-path",
            "fallback": "discovered split lacked a supported legal core",
        },
    )


def _path_payloads(
    con: duckdb.DuckDBPyConnection,
    hero_id: int,
    hero: dict[str, Any],
    paths: tuple[DiscoveredBuildPath, ...],
    inventories: dict[tuple[int, int], tuple[int, ...]],
    context: _HeroExportContext,
) -> list[dict[str, Any]]:
    labels = [_path_label(con, path, context.mechanics_assets_by_id) for path in paths]
    label_counts = Counter(labels)
    try:
        return [
            _build_path_payload(
                con,
                hero_id,
                hero,
                path,
                label,
                label_counts,
                inventories,
                context,
            )
            for path, label in zip(paths, labels, strict=True)
        ]
    except UnsupportedBuildPathError:
        if len(paths) == 1:
            raise
    fallback = _fallback_build_path(inventories, context.folds_by_match)
    return [
        _build_path_payload(
            con,
            hero_id,
            hero,
            fallback,
            DEFAULT_BUILD_PATH_LABEL,
            Counter({DEFAULT_BUILD_PATH_LABEL: 1}),
            inventories,
            context,
        )
    ]


def _build_hero_payload(
    job: tuple[int, dict[str, Any]],
    *,
    context: _HeroExportContext,
) -> dict[str, Any]:
    index, hero = job
    con = duckdb.connect(str(context.paths.raw / "analysis.duckdb"), read_only=True)
    con.execute("SET threads = 1")
    try:
        hero_id = int(hero["id"])
        name = str(hero.get("name") or hero_id)
        print(
            f"Production evidence {index}/{context.hero_count} started: {name}",
            flush=True,
        )
        inventories = _inventories_for_hero(con, hero_id, context.components)
        paths = discover_build_paths(
            inventories,
            _early_inventories_for_hero(con, hero_id),
            context.folds_by_match,
        )
        payload = {
            "hero_id": hero_id,
            "hero": name,
            "builds": _path_payloads(
                con,
                hero_id,
                hero,
                paths,
                inventories,
                context,
            ),
        }
        print(
            f"Production evidence {index}/{context.hero_count} completed: {name}",
            flush=True,
        )
        return payload
    finally:
        con.close()


def export_production_evidence(paths: RunPaths, output: Path) -> dict[str, Any]:
    manifest = read_json(paths.run / "manifest.json")
    cohort = manifest.get("cohort")
    sources = manifest.get("sources")
    if not isinstance(cohort, dict) or not isinstance(sources, dict):
        raise RuntimeError("analysis manifest lacks frozen cohort or source identity")
    as_of = datetime.fromisoformat(str(cohort["as_of"]))
    heroes = read_json(paths.raw / "heroes.json")
    items_all = read_json(paths.raw / "items-all.json")
    normal_assets = [
        item
        for item in items_all
        if isinstance(item, dict)
        and str(item.get("game_mode") or "normal").casefold() == "normal"
    ]
    item_assets, components = _asset_maps(paths.raw / "items.json")
    item_graph = ItemGraph.from_assets(list(item_assets.values()))
    mechanics_assets_by_id = {
        int(asset["id"]): asset
        for asset in normal_assets
        if isinstance(asset.get("id"), int)
    }
    item_costs = {
        item_id: int(asset.get("cost") or 0) for item_id, asset in item_assets.items()
    }
    con = duckdb.connect(str(paths.raw / "analysis.duckdb"), read_only=True)
    patch = _patch_at(paths, as_of)
    client_version = int(sources["client_version"])
    try:
        folds_by_match = _folds_by_match(con)
        core_economy_reference = _core_economy_reference(con, cohort)
    finally:
        con.close()

    export_context = _HeroExportContext(
        paths=paths,
        hero_count=len(heroes),
        components=components,
        folds_by_match=folds_by_match,
        normal_assets=normal_assets,
        item_graph=item_graph,
        mechanics_assets_by_id=mechanics_assets_by_id,
        item_costs=item_costs,
        target_core_cost=int(core_economy_reference["target_core_cost"]),
    )
    hero_payloads = _parallel_hero_export(
        list(enumerate(heroes, start=1)),
        partial(_build_hero_payload, context=export_context),
    )

    epochs = {
        name: {
            "identity": str(patch["identity"]),
            "start_timestamp": int(patch["start_timestamp"]),
        }
        for name in ("mechanics", "matchmaking", "map_objectives", "telemetry")
    }
    payload = {
        "schema_version": SCHEMA_VERSION,
        "producer": "deadlock-build-sync.offline",
        "method": {
            "version": METHOD_VERSION,
            "core_candidate_item_count": CORE_ITEM_COUNT,
            "minimum_core_item_count": 4,
            "maximum_core_item_count": BASE_INVENTORY_SLOTS,
            "core_candidate_limit": CORE_CANDIDATE_LIMIT,
            "minimum_core_support": MINIMUM_CORE_SUPPORT,
            "minimum_tier_support": SEQUENCE_MINIMUM_SUPPORT,
            "tier_item_count": TIER_ITEM_COUNT,
            "core_selection": (
                "temporally stable supported four-to-six-item backbone, then a "
                "jointly supported mechanically legal completion of up to nine items "
                "within ten percent of the Oracle I+ economy target when available"
            ),
            "tier_membership": (
                "player-match adoption descending after requiring every available "
                "higher upgrade tier to expose a supported continuation"
            ),
            "tier_display_order": "median valid pre-purchase net worth, then median buy time and item id",
            "core_economy_reference": core_economy_reference,
            "outcome_usage": (
                "cross-fitted doubly robust contrasts may admit optional final-slot "
                "alternatives after overlap, balance, ESS, uncertainty, and temporal "
                "stability gates; never represented as proof of causation"
            ),
        },
        "cohort": {
            **cohort,
            "minimum_badge": int(cohort["minimum_badge"]),
            "maximum_badge": int(cohort["maximum_badge"]),
        },
        "patch": patch,
        "epochs": epochs,
        "client_version": client_version,
        "rank_labels_sha256": _rank_labels_sha256(paths),
        "heroes_sha256": sha256_json(heroes),
        "items_sha256": sha256_json(normal_assets),
        "source_sha256": sources.get("source_sha256", {}),
        "frozen_data_sha256": manifest.get("frozen_data_sha256", {}),
        "requested_hero_ids": sorted(int(hero["id"]) for hero in heroes),
        "heroes": hero_payloads,
    }
    document = {**payload, "artifact_id": sha256_json(payload)}
    _atomic_write(output, document)
    return document
