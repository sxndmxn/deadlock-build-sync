from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from typing import TYPE_CHECKING

from deadlock_build_sync.value_validation import integer, object_list, object_rows

from .api import read_json

if TYPE_CHECKING:
    from pathlib import Path


def load_item_asset_maps(
    items_path: Path,
) -> tuple[dict[int, dict[str, object]], dict[int, tuple[int, ...]]]:
    """Load item assets and resolve their component item IDs."""
    items = object_rows(read_json(items_path))
    if items is None:
        raise TypeError("item assets must be a list of dictionaries")
    by_id = {integer(item["id"]): item for item in items}
    by_class = {
        str(item["class_name"]): item_id
        for item_id, item in by_id.items()
        if "class_name" in item
    }
    components: dict[int, tuple[int, ...]] = {}
    for item_id, item in by_id.items():
        component_names = object_list(item.get("component_items")) or []
        components[item_id] = tuple(
            by_class[name]
            for name in component_names
            if isinstance(name, str) and name in by_class
        )
    return by_id, components


def _component_depth(
    item_id: int,
    components: Mapping[int, tuple[int, ...]],
    depths: dict[int, int],
) -> int:
    if item_id not in depths:
        children = components.get(item_id, ())
        depths[item_id] = (
            1 + max(_component_depth(child, components, depths) for child in children)
            if children
            else 0
        )
    return depths[item_id]


def _apply_purchase_bucket(
    owned: list[int],
    item_ids: list[int],
    components: Mapping[int, tuple[int, ...]],
    depths: dict[int, int],
) -> None:
    for item_id in sorted(
        item_ids,
        key=lambda value: (_component_depth(value, components, depths), value),
    ):
        for component_id in components.get(item_id, ()):
            if component_id in owned:
                owned.remove(component_id)
        owned.append(item_id)


def _apply_removal_bucket(owned: list[int], item_ids: list[int]) -> None:
    for item_id in sorted(item_ids):
        if item_id in owned:
            owned.remove(item_id)


def reconstruct_final_inventory(
    purchases: list[tuple[int, int, int]],
    components: Mapping[int, tuple[int, ...]],
) -> tuple[int, ...]:
    """Replay timestamp buckets, component consumption, and sales to match end."""
    buys: dict[int, list[int]] = defaultdict(list)
    removals: dict[int, list[int]] = defaultdict(list)
    for item_id, buy_time, sold_time in purchases:
        buys[buy_time].append(item_id)
        if sold_time > 0:
            removals[sold_time].append(item_id)

    depths: dict[int, int] = {}
    owned: list[int] = []
    for timestamp in sorted(set(buys) | set(removals)):
        # The API only supplies second-resolution timestamps. Within one bucket,
        # dependency order is knowable but arbitrary item-ID order is not.
        _apply_purchase_bucket(owned, buys[timestamp], components, depths)
        # An explicit removal wins an unresolved buy/removal tie so a sold item
        # cannot be reconstructed as present at match end.
        _apply_removal_bucket(owned, removals[timestamp])
    return tuple(sorted(owned))
