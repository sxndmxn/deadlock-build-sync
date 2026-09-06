"""Asset loading and small sequence helpers for offline rankings."""

from dataclasses import dataclass

import polars as pl
from deadlock_build_sync.offline.api import read_json
from deadlock_build_sync.offline.config import RunPaths
from deadlock_build_sync.value_validation import (
    integer,
    object_list,
    object_rows,
)


def rows_frame(rows: list[dict[str, object]]) -> pl.DataFrame:
    return pl.DataFrame(rows, infer_schema_length=None)


def longest_common_subsequence(first: list[int], second: list[int]) -> int:
    lengths = [[0] * (len(second) + 1) for _ in range(len(first) + 1)]
    for first_index, first_item in enumerate(first, start=1):
        for second_index, second_item in enumerate(second, start=1):
            if first_item == second_item:
                lengths[first_index][second_index] = (
                    lengths[first_index - 1][second_index - 1] + 1
                )
            else:
                lengths[first_index][second_index] = max(
                    lengths[first_index - 1][second_index],
                    lengths[first_index][second_index - 1],
                )
    return lengths[-1][-1]


@dataclass(frozen=True)
class Asset:
    item_id: int
    name: str
    class_name: str
    tier: int
    cost: int
    active: bool
    components: tuple[str, ...]


def assets(paths: RunPaths) -> tuple[dict[int, Asset], dict[str, int]]:
    assets_by_id: dict[int, Asset] = {}
    by_class: dict[str, int] = {}
    rows = object_rows(read_json(paths.raw / "items.json"))
    if rows is None:
        raise TypeError("item assets are not an array of objects")
    for row in rows:
        asset = Asset(
            item_id=integer(row["id"]),
            name=str(row.get("name") or f"Item {row['id']}"),
            class_name=str(row.get("class_name") or ""),
            tier=integer(row["item_tier"]),
            cost=integer(row.get("cost"), default=0),
            active=bool(row.get("is_active_item")),
            components=tuple(
                str(value) for value in object_list(row.get("component_items")) or []
            ),
        )
        assets_by_id[asset.item_id] = asset
        if asset.class_name:
            by_class[asset.class_name] = asset.item_id
    return assets_by_id, by_class
