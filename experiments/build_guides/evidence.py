"""Outcome-blind item pools and placement evidence within discovered core owners."""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

import numpy as np

from experiments.identity_paths.purchase_data import quantiles

if TYPE_CHECKING:
    from pathlib import Path

    import duckdb

MIN_BUYERS = 20
MAX_PER_TIER = 10


def collect(con: duckdb.DuckDBPyConnection, directory: Path, row: dict) -> dict:
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE guide_owners AS
        SELECT match_id, player_slot, hero_id FROM read_parquet(?)
        WHERE partition='discovery' AND hero_id=? AND list_has_all(current_items, ?)
        """,
        [str(directory / "observations.parquet"), row["hero_id"], row["items"]],
    )
    population = con.execute("SELECT count(*) FROM guide_owners").fetchone()[0]
    rows = con.execute("""
        SELECT p.match_id, p.player_slot, p.item_id, p.buy_time,
               p.own_net_worth_at_buy, p.state_observed_at_s
        FROM purchases p JOIN guide_owners o USING(match_id, player_slot, hero_id)
        WHERE p.buy_time <= p.duration_s
        QUALIFY row_number() OVER (
            PARTITION BY p.match_id, p.player_slot, p.item_id
            ORDER BY p.buy_time, p.event_order
        ) = 1
        ORDER BY p.match_id, p.player_slot, p.item_id
    """).fetchall()
    return summarize(rows, population)


def summarize(rows: list[tuple], population: int) -> dict:
    times, wealths, histories = defaultdict(list), defaultdict(list), {}
    for match, slot, raw_item, bought, wealth, observed in rows:
        actor = (int(match), int(slot))
        item = int(raw_item)
        if item in histories.setdefault(actor, {}):
            raise ValueError("First-purchase evidence contains a duplicate player/item")
        histories[actor][item] = float(bought)
        times[item].append(float(bought))
        if wealth is not None and observed is not None and 0 < bought - observed <= 300:
            wealths[item].append(float(wealth))
    if len(histories) > population:
        raise ValueError("Purchase evidence exceeds the discovered-owner population")
    stats = {
        item: {
            "buyers": len(values),
            "adoption": len(values) / max(1, population),
            "time_seconds_q25_q50_q75": quantiles(values),
            "fresh_wealth_observations": len(wealths[item]),
            "net_worth_q25_q50_q75": quantiles(wealths[item]),
        }
        for item, values in times.items()
    }
    return {"population": population, "items": stats, "histories": histories}


def timing_policy(stats: dict) -> tuple[dict, dict]:
    priorities, bounds = {}, {}
    for item, evidence in stats.items():
        wealth = evidence["net_worth_q25_q50_q75"]
        reliable = (
            wealth is not None
            and evidence["fresh_wealth_observations"] >= MIN_BUYERS
            and evidence["fresh_wealth_observations"] / evidence["buyers"] >= 0.5
        )
        time = evidence["time_seconds_q25_q50_q75"][1]
        priorities[item] = (wealth[1] if reliable else float("inf"), time, item)
        if reliable:
            bounds[item] = (wealth[0], wealth[2])
    return priorities, bounds


def placement(item: int, path: list[int], evidence: dict) -> dict:
    """Count strict, adjacent observed anchors; tied or absent anchors add no vote.

    Returns:
        A supported checkpoint or unknown timing.

    """
    counts = [0] * (len(path) + 1)
    for history in evidence["histories"].values():
        bought = history.get(item)
        if bought is None:
            continue
        for index in range(len(counts)):
            left = history.get(path[index - 1]) if index else -1.0
            right = history.get(path[index]) if index < len(path) else float("inf")
            if left is not None and right is not None and left < bought < right:
                counts[index] += 1
    buyers = evidence["items"][item]["buyers"]
    anchor = int(np.argmax(counts))
    supported = (
        bool(path) and counts[anchor] >= MIN_BUYERS and counts[anchor] / buyers >= 0.1
    )
    return {
        "after_step": anchor if supported else None,
        "observed_after_step": anchor,
        "support": counts[anchor],
        "buyers": buyers,
        "supported": supported,
        "counts_by_checkpoint": counts,
        "basis": "observed adjacent first-purchase anchors"
        if supported
        else "Timing unknown; adjacent purchase evidence is insufficient",
    }
