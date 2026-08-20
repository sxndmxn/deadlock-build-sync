from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping
from itertools import combinations
from pathlib import Path
from typing import Any

import duckdb
import polars as pl

from .api import read_json, write_json
from .config import RunPaths


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


def _asset_maps(
    items_path: Path,
) -> tuple[dict[int, dict[str, Any]], dict[int, tuple[int, ...]]]:
    items = read_json(items_path)
    by_id = {int(item["id"]): item for item in items}
    by_class = {str(item["class_name"]): int(item["id"]) for item in items}
    components = {
        item_id: tuple(
            by_class[class_name]
            for class_name in item.get("component_items") or []
            if class_name in by_class
        )
        for item_id, item in by_id.items()
    }
    return by_id, components


def _top_itemset(
    inventories: list[tuple[int, ...]], size: int
) -> tuple[tuple[int, ...], int]:
    counts: Counter[tuple[int, ...]] = Counter()
    for inventory in inventories:
        distinct = tuple(sorted(set(inventory)))
        if len(distinct) >= size:
            counts.update(combinations(distinct, size))
    return counts.most_common(1)[0] if counts else ((), 0)


def analyze_late_game_inventory(
    paths: RunPaths, hero_id: int, minimum_net_worth: int
) -> dict[str, Any]:
    by_id, components = _asset_maps(paths.raw / "items.json")
    con = duckdb.connect(str(paths.raw / "analysis.duckdb"), read_only=True)
    try:
        cohort = (
            con
            .sql(
                f"""
            SELECT count(*) AS player_matches, avg(won::INTEGER) AS outcome_rate,
                   median(duration_s) AS median_duration_s,
                   quantile_cont(duration_s, 0.25) AS duration_q25_s,
                   quantile_cont(duration_s, 0.75) AS duration_q75_s,
                   median(final_net_worth) AS median_final_net_worth
            FROM player_matches
            WHERE hero_id = {hero_id} AND final_net_worth >= {minimum_net_worth}
            """
            )
            .pl()
            .row(0, named=True)
        )
        events = con.sql(
            f"""
            SELECT p.match_id, p.player_slot, p.item_id, p.buy_time, p.sold_time
            FROM purchases p
            JOIN player_matches m USING (match_id, player_slot, hero_id)
            WHERE p.hero_id = {hero_id}
              AND m.final_net_worth >= {minimum_net_worth}
            ORDER BY p.match_id, p.player_slot, p.buy_time, p.event_order
            """
        ).pl()
        purchase_metrics = con.sql(
            f"""
            SELECT p.item_id, any_value(p.item_name) AS item_name,
                   any_value(p.tier) AS tier, any_value(p.cost) AS cost,
                   count(*) AS buyer_matches, avg(p.won::INTEGER) AS outcome_rate,
                   median(p.buy_time) AS median_buy_time_s,
                   quantile_cont(p.buy_time, 0.25) AS buy_time_q25_s,
                   quantile_cont(p.buy_time, 0.75) AS buy_time_q75_s,
                   median(p.own_net_worth_at_buy) AS median_buy_net_worth,
                   quantile_cont(p.own_net_worth_at_buy, 0.25) AS buy_nw_q25,
                   quantile_cont(p.own_net_worth_at_buy, 0.75) AS buy_nw_q75,
                   count(p.own_net_worth_at_buy) / count(*) AS valid_buy_nw_share
            FROM first_purchases p
            JOIN player_matches m USING (match_id, player_slot, hero_id)
            WHERE p.hero_id = {hero_id}
              AND m.final_net_worth >= {minimum_net_worth}
            GROUP BY p.item_id
            """
        ).pl()
        late_purchase_row = con.sql(
            f"""
            SELECT count(DISTINCT (match_id, player_slot))
            FROM first_purchases
            WHERE hero_id = {hero_id}
              AND own_net_worth_at_buy >= {minimum_net_worth}
            """
        ).fetchone()
        if late_purchase_row is None:
            raise RuntimeError("late-purchase denominator query returned no row")
        late_purchase_denominator = int(late_purchase_row[0])
        late_purchases = con.sql(
            f"""
            SELECT item_id, any_value(item_name) AS item_name,
                   any_value(tier) AS tier, any_value(cost) AS cost,
                   count(DISTINCT (match_id, player_slot)) AS buyer_matches,
                   avg(won::INTEGER) AS observed_outcome_rate,
                   median(buy_time) AS median_buy_time_s,
                   median(own_net_worth_at_buy) AS median_buy_net_worth
            FROM first_purchases
            WHERE hero_id = {hero_id}
              AND own_net_worth_at_buy >= {minimum_net_worth}
            GROUP BY item_id ORDER BY buyer_matches DESC
            """
        ).pl()
    finally:
        con.close()

    grouped: dict[tuple[int, int], list[tuple[int, int, int]]] = defaultdict(list)
    for row in events.iter_rows(named=True):
        grouped[int(row["match_id"]), int(row["player_slot"])].append((
            int(row["item_id"]),
            int(row["buy_time"]),
            int(row["sold_time"]),
        ))
    inventories = [
        reconstruct_final_inventory(purchases, components)
        for purchases in grouped.values()
    ]
    cohort_matches = int(cohort["player_matches"])
    final_item_counts: Counter[int] = Counter(
        item_id for inventory in inventories for item_id in set(inventory)
    )
    final_items = pl.DataFrame([
        {
            "item_id": item_id,
            "final_owned_matches": count,
            "final_inventory_adoption": count / cohort_matches,
        }
        for item_id, count in final_item_counts.items()
    ]).join(purchase_metrics, on="item_id", how="left")
    final_items = final_items.with_columns(
        (pl.col("buyer_matches") / cohort_matches).alias("purchase_adoption")
    ).sort("final_inventory_adoption", descending=True)
    final_items.write_csv(
        paths.tables / f"late_game_hero_{hero_id}_{minimum_net_worth}_items.csv"
    )
    late_purchases = late_purchases.with_columns(
        (pl.col("buyer_matches") / late_purchase_denominator).alias(
            "share_of_late_buyers"
        ),
        (pl.col("buyer_matches") / cohort_matches).alias(
            "share_of_high_net_worth_cohort"
        ),
    )
    late_purchases.write_csv(
        paths.tables / f"late_game_hero_{hero_id}_{minimum_net_worth}_capstones.csv"
    )

    size_counts = Counter(len(inventory) for inventory in inventories)
    exact_counts = Counter(inventories)
    top_exact, top_exact_count = exact_counts.most_common(1)[0]
    top_eight, top_eight_count = _top_itemset(inventories, 8)
    top_nine, top_nine_count = _top_itemset(inventories, 9)

    def item_names(item_ids: tuple[int, ...]) -> list[str]:
        return [str(by_id[item_id].get("name") or item_id) for item_id in item_ids]

    result = {
        "hero_id": hero_id,
        "minimum_final_net_worth": minimum_net_worth,
        "cohort": cohort,
        "reconstructed_inventories": len(inventories),
        "inventory_size_distribution": [
            {
                "items": size,
                "matches": count,
                "share": count / len(inventories),
            }
            for size, count in sorted(size_counts.items())
        ],
        "modal_exact_inventory": {
            "item_ids": list(top_exact),
            "items": item_names(top_exact),
            "matches": top_exact_count,
            "share": top_exact_count / len(inventories),
        },
        "most_common_eight_item_core": {
            "item_ids": list(top_eight),
            "items": item_names(top_eight),
            "matches": top_eight_count,
            "share": top_eight_count / len(inventories),
        },
        "most_common_nine_item_core": {
            "item_ids": list(top_nine),
            "items": item_names(top_nine),
            "matches": top_nine_count,
            "share": top_nine_count / len(inventories),
        },
        "late_purchase_players": late_purchase_denominator,
        "most_common_purchases_after_threshold": late_purchases.head(10).to_dicts(),
    }
    write_json(
        paths.tables / f"late_game_hero_{hero_id}_{minimum_net_worth}.json",
        result,
    )
    return result
