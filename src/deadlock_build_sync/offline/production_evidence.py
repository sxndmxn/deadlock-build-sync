from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from collections import Counter
from datetime import datetime
from itertools import combinations
from operator import itemgetter
from pathlib import Path
from typing import Any

import duckdb
import polars as pl

from deadlock_build_sync.build_evidence import (
    MAX_COMPARATIVE_INTERVAL_WIDTH,
    MAX_SITUATIONAL_BRANCHES,
    MECHANIC_RESPONSE_THREATS,
    SEQUENCE_POLICY_VERSION,
    THREAT_CLASSES,
)
from deadlock_build_sync.mechanics import (
    ItemGraph,
    classify_item_threat_responses,
    schedule_component_path,
)

from .api import read_json
from .config import RunPaths, sha256_json
from .late_game import _asset_maps, reconstruct_final_inventory

SCHEMA_VERSION = 2
CORE_ITEM_COUNT = 8
CORE_CANDIDATE_LIMIT = 64
TIER_ITEM_COUNT = 10
MINIMUM_CORE_SUPPORT = 20
METHOD_VERSION = "reconstructed-final-inventory-v3"
SEQUENCE_MINIMUM_SUPPORT = 20
_STEAM_CDN_HOST_PATTERN = re.compile(
    r"(?<=://)(clan|shared)\.(?:akamai|fastly)\.steamstatic\.com",
    re.IGNORECASE,
)


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


def _top_core_candidates(
    inventories: list[tuple[int, ...]],
    item_costs: dict[int, int],
    maximum_cost: int,
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
        candidates.append({"item_ids": list(item_ids), "joint_matches": matches})
        if len(candidates) == CORE_CANDIDATE_LIMIT:
            break
    return candidates


def _inventories_for_hero(
    con: duckdb.DuckDBPyConnection,
    hero_id: int,
    components: dict[int, tuple[int, ...]],
) -> list[tuple[int, ...]]:
    cursor = con.execute(
        f"""
        SELECT match_id, player_slot, item_id, buy_time, sold_time
        FROM purchases
        WHERE hero_id = {hero_id}
        ORDER BY match_id, player_slot, buy_time, event_order
        """
    )
    inventories: list[tuple[int, ...]] = []
    current: tuple[int, int] | None = None
    purchases: list[tuple[int, int, int]] = []
    while rows := cursor.fetchmany(100_000):
        for match_id, player_slot, item_id, buy_time, sold_time in rows:
            identity = int(match_id), int(player_slot)
            if current is not None and identity != current:
                inventories.append(reconstruct_final_inventory(purchases, components))
                purchases = []
            current = identity
            purchases.append((int(item_id), int(buy_time), int(sold_time)))
    if current is not None:
        inventories.append(reconstruct_final_inventory(purchases, components))
    return inventories


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


def _expanded_default_path(
    core_candidates: list[dict[str, Any]],
    hero_metrics: pl.DataFrame,
    graph: ItemGraph,
) -> list[int]:
    if not core_candidates:
        raise RuntimeError("hero has no supported eight-item core")
    evidence = {int(row["item_id"]): row for row in hero_metrics.iter_rows(named=True)}
    core = sorted(
        (int(item_id) for item_id in core_candidates[0]["item_ids"]),
        key=lambda item_id: (
            float(evidence[item_id].get("median_valid_buy_net_worth") or float("inf")),
            float(evidence[item_id].get("median_buy_time_s") or float("inf")),
            item_id,
        ),
    )
    priorities = {
        item_id: (
            float(row.get("median_valid_buy_net_worth") or float("inf")),
            float(row.get("median_buy_time_s") or float("inf")),
            item_id,
        )
        for item_id, row in evidence.items()
    }
    return list(schedule_component_path(graph, core, priorities))


def _sequence_rows(
    con: duckdb.DuckDBPyConnection,
    hero_id: int,
) -> list[dict[str, Any]]:
    rows = con.execute(
        """
        WITH numbered AS (
            SELECT match_id, player_slot, item_id,
                   row_number() OVER (
                       PARTITION BY match_id, player_slot ORDER BY buy_time, item_id
                   ) - 1 AS position,
                   lag(item_id, 1, 0) OVER (
                       PARTITION BY match_id, player_slot ORDER BY buy_time, item_id
                   ) AS previous_item_id,
                   first_value(item_id) OVER (
                       PARTITION BY match_id, player_slot ORDER BY buy_time, item_id
                   ) AS observed_first_item_id
            FROM first_purchases
            WHERE fold = 'train' AND hero_id = ?
        )
        SELECT CASE WHEN position = 0 THEN 0 ELSE observed_first_item_id END,
               previous_item_id, position, item_id
        FROM numbered
        ORDER BY match_id, player_slot, position
        """,
        [hero_id],
    ).fetchall()
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


def _challenger(paths: RunPaths) -> dict[str, Any]:
    path = paths.run / "xgboost/xgb_experiment_manifest.json"
    if not path.is_file():
        return {
            "evaluated": False,
            "passed": False,
            "promoted": False,
            "reason": "no chronological challenger artifact",
        }
    manifest = read_json(path)
    gate = manifest.get("promotion_gate")
    passed = bool(gate.get("passed")) if isinstance(gate, dict) else False
    return {
        "evaluated": True,
        "passed": passed,
        "promoted": False,
        "selected_model": manifest.get("selected_model"),
        "experiment_sha256": manifest.get("experiment_sha256"),
        "reason": (
            "portable validated policy export is not available"
            if passed
            else "predeclared chronological promotion gate failed"
        ),
    }


def _situational_policy(
    paths: RunPaths,
    hero_id: int,
    assets: list[dict[str, Any]],
    *,
    excluded_item_ids: frozenset[int] = frozenset(),
) -> dict[str, Any]:
    matchup_path = paths.tables / "matchup_interactions.csv"
    overlap_path = paths.tables / "state_overlap_diagnostics.csv"
    stability_path = paths.tables / "matchup_temporal_stability.csv"
    asset_by_id = {
        int(asset["id"]): asset for asset in assets if isinstance(asset.get("id"), int)
    }
    candidates: list[dict[str, Any]] = []
    qualified: list[tuple[tuple[float, ...], dict[str, Any], dict[str, Any]]] = []
    if matchup_path.is_file() and overlap_path.is_file() and stability_path.is_file():
        matchups = pl.read_csv(matchup_path).filter(pl.col("hero_id") == hero_id)
        overlap = pl.read_csv(overlap_path).filter(pl.col("hero_id") == hero_id)
        stability = pl.read_csv(stability_path).filter(pl.col("hero_id") == hero_id)
        overlap_by_item = {
            int(row["item_id"]): row for row in overlap.iter_rows(named=True)
        }
        stability_by_scope = {
            str(row["scope"]): row for row in stability.iter_rows(named=True)
        }
        for row in matchups.iter_rows(named=True):
            item_id = int(row["item_id"])
            if item_id in excluded_item_ids:
                continue
            asset = asset_by_id.get(item_id)
            if asset is None:
                continue
            responses = classify_item_threat_responses(asset)
            diagnostic = overlap_by_item.get(item_id, {})
            temporal = stability_by_scope.get(str(row["scope"]), {})
            for response in sorted(responses):
                effective = float(diagnostic.get("effective_support") or 0.0)
                state_coverage = float(diagnostic.get("state_coverage") or 0.0)
                comparator_item_id = int(row.get("comparator_item_id") or 0)
                comparison_support = int(row.get("comparison_support") or 0)
                interval_low = row.get("comparative_interval_low")
                interval_high = row.get("comparative_interval_high")
                bounded_uncertainty = (
                    isinstance(interval_low, (int, float))
                    and isinstance(interval_high, (int, float))
                    and math.isfinite(float(interval_low))
                    and math.isfinite(float(interval_high))
                    and float(interval_low) <= float(interval_high)
                    and float(interval_high) - float(interval_low)
                    <= MAX_COMPARATIVE_INTERVAL_WIDTH
                )
                comparative_interval = (
                    (float(interval_low), float(interval_high))
                    if bounded_uncertainty
                    and interval_low is not None
                    and interval_high is not None
                    else None
                )
                comparative_advantage = (
                    comparative_interval is not None and comparative_interval[0] > 0
                )
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
                    "bounded_comparative_uncertainty": bounded_uncertainty,
                    "comparative_advantage": comparative_advantage,
                }
                passed = all(gates.values())
                candidate = {
                    "threat": MECHANIC_RESPONSE_THREATS[response],
                    "item_id": item_id,
                    "comparator_item_id": comparator_item_id or None,
                    "enemy_hero_id": int(row["enemy_hero_id"]),
                    "scope": str(row["scope"]),
                    "mechanic_ref": f"item/{item_id}/{response}",
                    "comparator": (
                        f"same-opportunity item {comparator_item_id} or save"
                        if comparator_item_id
                        else "unavailable"
                    ),
                    "support": int(row["observations"]),
                    "comparison_support": comparison_support,
                    "effective_support": effective,
                    "overlap": state_coverage,
                    "stable": stable,
                    "comparative_interval": [interval_low, interval_high],
                    "gates": gates,
                    "qualified": passed,
                    "admitted": False,
                }
                candidates.append(candidate)
                if passed and comparative_interval is not None:
                    threat = MECHANIC_RESPONSE_THREATS[response]
                    enemy_id = int(row["enemy_hero_id"])
                    branch = {
                        "threat": threat,
                        "item_id": item_id,
                        "enemy_hero_id": enemy_id,
                        "mechanic_ref": f"item/{item_id}/{response}",
                        "comparator": candidate["comparator"],
                        "comparator_item_id": comparator_item_id,
                        "comparison_support": comparison_support,
                        "same_opportunity": True,
                        "support": int(row["observations"]),
                        "effective_support": effective,
                        "overlap": state_coverage,
                        "stable": stable,
                        "comparative_interval": list(comparative_interval),
                        "trigger": (
                            f"Enemy hero {enemy_id} presents material "
                            f"{threat.replace('_', ' ')}."
                        ),
                        "replacement": (
                            f"Choose item {item_id} instead of item "
                            f"{comparator_item_id} at the matched opportunity."
                        ),
                        "execution": (
                            f"Use the verified {response.replace('_', ' ')} mechanic "
                            "while the trigger remains observable."
                        ),
                        "failure_condition": (
                            "Skip when the threat is not material or the compared "
                            "decision state no longer matches."
                        ),
                    }
                    score = (
                        float(str(row["scope"]) == "same_lane"),
                        state_coverage,
                        effective,
                        float(row["observations"]),
                        -float(item_id),
                    )
                    qualified.append((score, candidate, branch))
    ordered = sorted(
        qualified,
        key=lambda row: (
            tuple(-value for value in row[0]),
            str(row[2]["threat"]),
            int(row[2]["enemy_hero_id"]),
            int(row[2]["item_id"]),
        ),
    )
    branches = []
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
    rejected = len(candidates) - len(branches)
    return {
        "version": 1,
        "threat_vocabulary": sorted(THREAT_CLASSES),
        "branches": branches,
        "candidate_audit": candidates,
        "abstentions": (
            [
                f"{rejected} mechanics-backed candidate(s) failed at least one same-opportunity, comparator, support, overlap, bounded-uncertainty, or chronological-stability gate."
            ]
            if rejected
            else (
                ["No mechanics-backed situational candidate was available."]
                if not branches
                else []
            )
        ),
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
    item_costs = {
        item_id: int(asset.get("cost") or 0) for item_id, asset in item_assets.items()
    }
    metrics = pl.read_csv(paths.tables / "item_metrics.csv")
    challenger = _challenger(paths)
    con = duckdb.connect(str(paths.raw / "analysis.duckdb"), read_only=True)
    hero_payloads = []
    try:
        for index, hero in enumerate(heroes, start=1):
            hero_id = int(hero["id"])
            print(
                f"Production evidence {index}/{len(heroes)}: "
                f"{hero.get('name') or hero_id}",
                flush=True,
            )
            inventories = _inventories_for_hero(con, hero_id, components)
            cohort_row = con.execute(
                f"""
                SELECT count(*), median(final_net_worth)
                FROM player_matches WHERE hero_id = {hero_id}
                """
            ).fetchone()
            if cohort_row is None or cohort_row[1] is None:
                raise RuntimeError(f"hero {hero_id} has no cohort summary")
            hero_metrics = metrics.filter(pl.col("hero_id") == hero_id)
            core_candidates = _top_core_candidates(
                inventories,
                item_costs,
                int(cohort_row[1]),
            )
            hero_payloads.append({
                "hero_id": hero_id,
                "hero": str(hero.get("name") or hero_id),
                "eligible_player_matches": int(cohort_row[0]),
                "median_final_net_worth": int(cohort_row[1]),
                "core_candidates": core_candidates,
                "items": [
                    _item_payload(row)
                    for row in hero_metrics.sort("item_id").iter_rows(named=True)
                ],
                "sequence_policy": {
                    "version": SEQUENCE_POLICY_VERSION,
                    "minimum_support": SEQUENCE_MINIMUM_SUPPORT,
                    "production_model": "deterministic_backoff",
                    "component_expanded_default_path": _expanded_default_path(
                        core_candidates,
                        hero_metrics,
                        item_graph,
                    ),
                    "transitions": _sequence_rows(con, hero_id),
                    "evaluation": {
                        "chronological_fold": "test",
                        "metrics": _sequence_evaluation(paths, hero_id),
                        "claim": "outcome-agnostic next-action imitation",
                    },
                    "challenger": challenger,
                },
                "situational_policy": _situational_policy(
                    paths,
                    hero_id,
                    normal_assets,
                    excluded_item_ids=frozenset(core_candidates[0]["item_ids"]),
                ),
            })
    finally:
        con.close()

    patch = _patch_at(paths, as_of)
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
            "core_item_count": CORE_ITEM_COUNT,
            "core_candidate_limit": CORE_CANDIDATE_LIMIT,
            "minimum_core_support": MINIMUM_CORE_SUPPORT,
            "minimum_tier_support": SEQUENCE_MINIMUM_SUPPORT,
            "tier_item_count": TIER_ITEM_COUNT,
            "core_selection": "within median final net worth, joint support descending, then item ids",
            "tier_membership": "player-match adoption descending, then support and item id",
            "tier_display_order": "median valid pre-purchase net worth, then median buy time and item id",
            "outcome_usage": "descriptive only; never selection or ordering",
        },
        "cohort": {
            **cohort,
            "minimum_badge": int(cohort["minimum_badge"]),
            "maximum_badge": int(cohort["maximum_badge"]),
        },
        "patch": patch,
        "epochs": epochs,
        "client_version": int(sources["client_version"]),
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
