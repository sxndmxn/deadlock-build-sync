"""Reconstruct inventories and team observations before each purchase checkpoint."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from deadlock_build_sync.mechanics import ItemGraph
from deadlock_build_sync.value_validation import integer, number

from .inventory_reconstruction import InventoryTimeline, reconstruct_final_inventory
from .purchase_event_table import PurchaseEventTable
from .sql_resources import load_sql

if TYPE_CHECKING:
    import duckdb


def load_decision_rows(
    connection: duckdb.DuckDBPyConnection,
    hero: int,
    minimum: int = 11,
    maximum: int = 116,
) -> list[dict[str, object]]:
    cursor = connection.execute(
        load_sql("discovery/select_decision_rows.sql"),
        {"hero": hero, "minimum": minimum, "maximum": maximum},
    )
    names = [column[0] for column in cursor.description]
    result = []
    while rows := cursor.fetchmany(8192):
        result.extend(dict(zip(names, values, strict=True)) for values in rows)
    return result


def load_purchase_event_histories(
    connection: duckdb.DuckDBPyConnection,
    hero: int,
    minimum: int = 11,
    maximum: int = 116,
) -> PurchaseEventTable:
    cursor = connection.execute(
        load_sql("discovery/select_purchase_event_histories.sql"),
        {"hero": hero, "minimum": minimum, "maximum": maximum},
    )
    columns = cursor.fetchnumpy()
    if any(np.ma.is_masked(column) for column in columns.values()):
        raise ValueError("Purchase histories contain incomplete identifiers or times")
    return PurchaseEventTable(
        columns["match_id"],
        columns["player_slot"],
        np.column_stack([
            columns[name] for name in ("team_id", "item_id", "buy_time", "sold_time")
        ]),
    )


def reconstruct_inventory_before(
    events: list[tuple[int, int, int, int]], clock: int, graph: ItemGraph
) -> tuple[int, ...]:
    return reconstruct_final_inventory(
        [
            (item, bought, sold if 0 < sold < clock else 0)
            for _, item, bought, sold in events
            if bought < clock
        ],
        graph.components,
    )


def load_checkpoint_rows(
    connection: duckdb.DuckDBPyConnection,
    hero: int,
    graph: ItemGraph,
    minimum: int = 11,
    maximum: int = 116,
) -> list[dict[str, object]]:
    decisions = load_decision_rows(connection, hero, minimum, maximum)
    histories = load_purchase_event_histories(connection, hero, minimum, maximum)
    enemy_inventory_cache: dict[tuple[int, int, int], list[int]] = {}
    inventories: dict[int, tuple[int, InventoryTimeline]] = {}
    previous_match: int | None = None
    for row in decisions:
        clock = integer(row["buy_time"])
        match, slot, team = (
            integer(row["match_id"]),
            integer(row["player_slot"]),
            integer(row["team_id"]),
        )
        if match != previous_match:
            enemy_inventory_cache.clear()
            inventories = _prepare_match_inventories(histories.for_match(match), graph)
            previous_match = match
        own_inventory = inventories.get(slot)
        row["owned_before"] = (
            list(own_inventory[1].before(clock)) if own_inventory is not None else []
        )
        enemy_observed = row.get("enemy_observed")
        fresh_enemy = (
            enemy_observed is not None and 0 < clock - integer(enemy_observed) <= 300
        )
        enemies: list[int] = []
        if fresh_enemy:
            key = match, team, integer(enemy_observed)
            if key not in enemy_inventory_cache:
                enemy_inventory_cache[key] = _reconstruct_enemy_inventory(
                    inventories, team, integer(enemy_observed) + 1
                )
            enemies = enemy_inventory_cache[key]
        if not fresh_enemy:
            row["enemy_heroes"] = []
        row["enemy_items"] = list(enemies)
        row["fold"] = "train" if row["partition"] == "discovery" else "validation"
        row["relative_wealth"] = _calculate_relative_wealth(row, clock)
    return decisions


def _prepare_match_inventories(
    histories: dict[int, list[tuple[int, int, int, int]]],
    graph: ItemGraph,
) -> dict[int, tuple[int, InventoryTimeline]]:
    return {
        slot: (
            events[0][0],
            InventoryTimeline(
                [(item, bought, sold) for _, item, bought, sold in events],
                graph.components,
            ),
        )
        for slot, events in histories.items()
        if events
    }


def _reconstruct_enemy_inventory(
    inventories: dict[int, tuple[int, InventoryTimeline]], team: int, clock: int
) -> list[int]:
    return sorted({
        item
        for owner_team, inventory in inventories.values()
        if owner_team != team
        for item in inventory.before(clock)
    })


def _calculate_relative_wealth(row: dict[str, object], clock: int) -> float | None:
    complete = (
        row.get("own_team_observed_players") == 6
        and row.get("enemy_team_observed_players") == 6
        and row.get("own_observed") is not None
        and row.get("enemy_observed") is not None
        and 0 < clock - integer(row["own_observed"]) <= 300
        and 0 < clock - integer(row["enemy_observed"]) <= 300
    )
    total = number(row.get("own_team_net_worth") or 0) + number(
        row.get("enemy_team_net_worth") or 0
    )
    return (
        number(row["own_net_worth_at_buy"]) * 12 / total
        if complete and total > 0
        else None
    )
