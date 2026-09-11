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
)
from deadlock_build_sync.value_validation import (
    integer,
    object_dict,
    object_rows,
)

from .api import read_json
from .config import RunPaths, sha256_json
from .sql_resources import load_sql

if TYPE_CHECKING:
    import duckdb

SCHEMA_VERSION = BUILD_EVIDENCE_SCHEMA_VERSION
MINIMUM_CORE_SUPPORT = 20
SEQUENCE_MINIMUM_SUPPORT = 20
_STEAM_CDN_HOST_PATTERN = re.compile(
    r"(?<=://)(clan|shared)\.(?:akamai|fastly)\.steamstatic\.com",
    re.IGNORECASE,
)


class UnsupportedBuildPathError(ValueError):
    """Raised when a discovered item path cannot produce a supported legal core."""


@dataclass(frozen=True)
class _HeroExportContext:
    paths: RunPaths
    normal_assets: list[dict[str, object]]
    item_graph: ItemGraph
    mechanics_assets_by_id: dict[int, dict[str, object]]
    target_core_cost: int
    minimum_badge: int = 71
    maximum_badge: int = 115
    rank_expansion: str = "auto"


def _normalize_patch_guid(value: object) -> str:
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


def _calculate_patch_content_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            _normalize_patch_content(value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    ).hexdigest()


def _select_patch_at_timestamp(paths: RunPaths, as_of: datetime) -> dict[str, object]:
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
    content_sha256 = _calculate_patch_content_sha256(selected.get("content"))
    patch = {
        "title": str(selected.get("title") or "Current patch"),
        "start_timestamp": int(published.timestamp()),
        "published_at": str(selected["pub_date"]),
        "source": str(selected.get("source") or "unknown"),
        "guid": _normalize_patch_guid(selected.get("guid")),
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


def _calculate_rank_labels_sha256(paths: RunPaths) -> str:
    rows = object_rows(read_json(paths.raw / "ranks.json")) or []
    labels = {
        integer(row["tier"]): str(row["name"]).strip()
        for row in rows
        if isinstance(row.get("tier"), int)
        and isinstance(row.get("name"), str)
        and str(row["name"]).strip()
    }
    return sha256_json(labels)


def _query_path_item_metrics(
    connection: duckdb.DuckDBPyConnection,
    member_ids: frozenset[tuple[int, int]],
    hero: int,
) -> pl.DataFrame:
    members = pl.DataFrame({
        "match_id": [identity[0] for identity in member_ids],
        "player_slot": [identity[1] for identity in member_ids],
    })
    connection.register("_build_path_members", members)
    try:
        return connection.sql(
            load_sql("production/select_path_item_metrics.sql"),
            params={
                "hero": hero,
                "minimum_support": MINIMUM_CORE_SUPPORT,
                "member_count": len(member_ids),
            },
        ).pl()
    finally:
        connection.unregister("_build_path_members")
