"""Freeze outcome-blind optional purchase positions within each build cohort."""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl

from deadlock_build_sync.value_validation import (
    integer,
    number,
    object_dict,
    object_list,
)

if TYPE_CHECKING:
    import duckdb


def timing_payload(
    con: duckdb.DuckDBPyConnection,
    hero_id: int,
    members: frozenset[tuple[int, int]],
    path: tuple[int, ...],
    tier_policy: dict[str, object],
) -> dict[str, object]:
    pool = object_dict(tier_policy["item_ids_by_tier"]) or {}
    item_ids = sorted({
        integer(item) for values in pool.values() for item in object_list(values) or []
    })
    con.register(
        "_timing_members",
        pl.DataFrame({
            "match_id": [row[0] for row in members],
            "player_slot": [row[1] for row in members],
        }),
    )
    try:
        rows = con.execute(
            """
            SELECT p.match_id, p.player_slot, p.item_id, min(p.buy_time)
            FROM first_purchases p JOIN _timing_members m USING (match_id, player_slot)
            WHERE p.hero_id = ? AND p.fold = 'train'
            GROUP BY p.match_id, p.player_slot, p.item_id
        """,
            [hero_id],
        ).fetchall()
    finally:
        con.unregister("_timing_members")
    histories: dict[tuple[int, int], dict[int, float]] = {}
    for match_id, player_slot, item, bought in rows:
        histories.setdefault((integer(match_id), integer(player_slot)), {})[
            integer(item)
        ] = number(bought)
    results = _interval_counts(item_ids, path, histories)
    return {"version": 1, "fold": "train", "core_path": list(path), "items": results}


def _interval_counts(
    item_ids: list[int],
    path: tuple[int, ...],
    histories: dict[tuple[int, int], dict[int, float]],
) -> list[dict[str, object]]:
    return [_item_counts(item, path, histories) for item in item_ids]


def _item_counts(
    item: int, path: tuple[int, ...], histories: dict[tuple[int, int], dict[int, float]]
) -> dict[str, object]:
    counts = [0] * (len(path) + 1)
    buyers = 0
    for history in histories.values():
        bought = history.get(item)
        if bought is None:
            continue
        buyers += 1
        for position in range(len(counts)):
            left = history.get(path[position - 1]) if position else -1.0
            right = (
                history.get(path[position]) if position < len(path) else float("inf")
            )
            if left is not None and right is not None and left < bought < right:
                counts[position] += 1
    return {"item_id": item, "buyers": buyers, "counts_by_checkpoint": counts}
