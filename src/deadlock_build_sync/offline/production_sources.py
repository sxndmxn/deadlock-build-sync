from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from operator import itemgetter
from typing import TYPE_CHECKING

import polars as pl

from deadlock_build_sync.build_evidence import (
    BUILD_EVIDENCE_SCHEMA_VERSION,
)
from deadlock_build_sync.mechanics import (
    ItemGraph,
    classify_observed_item_threats,
)
from deadlock_build_sync.mechanics_compatibility import (
    asset_mechanics_refs,
)
from deadlock_build_sync.value_validation import (
    integer,
    object_dict,
    object_rows,
)

from .api import read_json
from .config import RunPaths, sha256_json
from .late_game import reconstruct_final_inventory
from .sql_fragments import ITEM_OUTCOME_AGGREGATES_SQL

if TYPE_CHECKING:
    import duckdb

SCHEMA_VERSION = BUILD_EVIDENCE_SCHEMA_VERSION
MINIMUM_CORE_SUPPORT = 20
HERO_EXPORT_WORKERS = 8
SEQUENCE_MINIMUM_SUPPORT = 20
CORE_ECONOMY_REFERENCE_MINIMUM_BADGE = 81
DEFAULT_BUILD_PATH_LABEL = "Evidence Default"
_STEAM_CDN_HOST_PATTERN = re.compile(
    r"(?<=://)(clan|shared)\.(?:akamai|fastly)\.steamstatic\.com",
    re.IGNORECASE,
)


class UnsupportedBuildPathError(ValueError):
    """Raised when a discovered item path cannot produce a supported legal core."""


@dataclass(frozen=True)
class _HeroExportContext:
    paths: RunPaths
    hero_count: int
    components: dict[int, tuple[int, ...]]
    folds_by_match: dict[int, str]
    normal_assets: list[dict[str, object]]
    item_graph: ItemGraph
    mechanics_assets_by_id: dict[int, dict[str, object]]
    item_costs: dict[int, int]
    target_core_cost: int
    enemy_threat_evidence: dict[int, dict[str, tuple[str, ...]]]


def _hero_threat_refs(
    hero: dict[str, object],
    assets_by_class: dict[str, dict[str, object]],
) -> tuple[int, dict[str, tuple[str, ...]]] | None:
    hero_id = hero.get("id")
    signatures = object_dict(hero.get("items"))
    if not isinstance(hero_id, int) or signatures is None:
        return None
    refs_by_threat: dict[str, set[str]] = {}
    for class_name in signatures.values():
        if not isinstance(class_name, str):
            continue
        asset = assets_by_class.get(class_name)
        if asset is None:
            continue
        refs = asset_mechanics_refs(asset)
        for threat in classify_observed_item_threats(asset):
            refs_by_threat.setdefault(threat, set()).update(refs)
    refs = {
        threat: tuple(sorted(values))
        for threat, values in refs_by_threat.items()
        if values
    }
    return (hero_id, refs) if refs else None


def _enemy_threat_evidence(
    heroes: list[dict[str, object]],
    assets: list[dict[str, object]],
) -> dict[int, dict[str, tuple[str, ...]]]:
    by_class = {
        str(asset["class_name"]): asset
        for asset in assets
        if isinstance(asset.get("class_name"), str)
    }
    result: dict[int, dict[str, tuple[str, ...]]] = {}
    for hero in heroes:
        row = _hero_threat_refs(hero, by_class)
        if row is not None:
            hero_id, refs = row
            result[hero_id] = refs
    return result


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


def _normalize_patch_content(value: object) -> object:
    if isinstance(value, str):
        return _STEAM_CDN_HOST_PATTERN.sub(r"\1.cdn.steamstatic.com", value)
    if isinstance(value, list):
        return [_normalize_patch_content(nested) for nested in value]
    if isinstance(value, dict):
        return {
            str(key): _normalize_patch_content(nested) for key, nested in value.items()
        }
    return value


def _patch_content_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            _normalize_patch_content(value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    ).hexdigest()


def _patch_at(paths: RunPaths, as_of: datetime) -> dict[str, object]:
    payload = read_json(paths.raw / "patches.json")
    payload_object = object_dict(payload)
    if payload_object is not None:
        payload = payload_object.get("patches") or payload_object.get("data")
    rows = object_rows(payload)
    if rows is None:
        raise RuntimeError("patch source does not contain a patch list")
    candidates: list[tuple[datetime, dict[str, object]]] = []
    for row in rows:
        published_at = row.get("pub_date")
        if not isinstance(published_at, str):
            continue
        published = datetime.fromisoformat(published_at)
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
    rows = object_rows(read_json(paths.raw / "ranks.json")) or []
    labels = {
        integer(row["tier"]): str(row["name"]).strip()
        for row in rows
        if isinstance(row.get("tier"), int)
        and isinstance(row.get("name"), str)
        and str(row["name"]).strip()
    }
    return sha256_json(labels)


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
            ), imbue_counts AS (
                SELECT p.item_id, p.imbued_ability_id,
                       count(*) AS target_matches
                FROM first_purchases p
                JOIN _build_path_members m USING (match_id, player_slot)
                WHERE p.imbued_ability_id > 0
                  AND p.fold IN ('train', 'validation')
                GROUP BY p.item_id, p.imbued_ability_id
            ), ranked_imbues AS (
                SELECT *,
                       sum(target_matches) OVER (PARTITION BY item_id)
                           AS imbue_observations,
                       row_number() OVER (
                           PARTITION BY item_id
                           ORDER BY target_matches DESC, imbued_ability_id
                       ) AS target_rank
                FROM imbue_counts
            ), dominant_imbues AS (
                SELECT item_id, imbued_ability_id, target_matches,
                       imbue_observations,
                       target_matches / imbue_observations::DOUBLE AS target_share
                FROM ranked_imbues
                WHERE target_rank = 1
            ), items AS (
                SELECT
                    p.hero_id, p.item_id, any_value(p.item_name) AS item_name,
                    any_value(p.tier) AS tier, any_value(p.cost) AS cost,
                    any_value(p.slot) AS slot, any_value(p.active) AS active,
                    count(*) AS adopter_matches,
                    count(*) FILTER (
                        WHERE p.fold IN ('train', 'validation')
                    ) AS selection_adopter_matches,
                    count(*) FILTER (
                        WHERE p.fold = 'train'
                    ) AS training_adopter_matches,
                    count(*) FILTER (
                        WHERE p.fold = 'validation'
                    ) AS validation_adopter_matches,
                    count(*) FILTER (
                        WHERE p.fold = 'test'
                    ) AS test_adopter_matches,
                    {ITEM_OUTCOME_AGGREGATES_SQL},
                    median(p.buy_time) FILTER (
                        WHERE p.fold IN ('train', 'validation')
                    ) AS selection_median_buy_time_s,
                    median(p.own_net_worth_at_buy) FILTER (
                        WHERE p.fold IN ('train', 'validation')
                    ) AS selection_median_valid_buy_net_worth,
                    quantile_cont(p.own_net_worth_at_buy, 0.25) FILTER (
                        WHERE p.fold IN ('train', 'validation')
                    ) AS selection_buy_nw_q25,
                    quantile_cont(p.own_net_worth_at_buy, 0.75) FILTER (
                        WHERE p.fold IN ('train', 'validation')
                    ) AS selection_buy_nw_q75,
                    count(p.own_net_worth_at_buy) FILTER (
                        WHERE p.fold IN ('train', 'validation')
                    ) AS selection_valid_buy_nw_observations,
                    count(p.own_net_worth_at_buy) FILTER (
                        WHERE p.fold = 'train'
                    ) AS training_valid_buy_nw_observations,
                    count(p.own_net_worth_at_buy) FILTER (
                        WHERE p.fold = 'validation'
                    ) AS validation_valid_buy_nw_observations,
                    quantile_cont(p.own_net_worth_at_buy, 0.25) FILTER (
                        WHERE p.fold = 'train'
                    ) AS training_buy_nw_q25,
                    quantile_cont(p.own_net_worth_at_buy, 0.75) FILTER (
                        WHERE p.fold = 'train'
                    ) AS training_buy_nw_q75,
                    quantile_cont(p.own_net_worth_at_buy, 0.25) FILTER (
                        WHERE p.fold = 'validation'
                    ) AS validation_buy_nw_q25,
                    quantile_cont(p.own_net_worth_at_buy, 0.75) FILTER (
                        WHERE p.fold = 'validation'
                    ) AS validation_buy_nw_q75
                FROM first_purchases p
                JOIN _build_path_members m USING (match_id, player_slot)
                GROUP BY p.hero_id, p.item_id
                HAVING count(*) >= {MINIMUM_CORE_SUPPORT}
            )
            SELECT i.*, e.purchase_events,
                   d.imbued_ability_id, d.target_matches,
                   d.imbue_observations, d.target_share,
                   {len(member_ids)}::BIGINT AS hero_player_matches,
                   i.adopter_matches / {len(member_ids)}::DOUBLE AS adoption_rate
            FROM items i JOIN events e USING (item_id)
            LEFT JOIN dominant_imbues d USING (item_id)
            """
        ).pl()
    finally:
        con.unregister("_build_path_members")
