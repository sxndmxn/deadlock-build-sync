"""Discovery-only event windows from original match/player purchase histories."""

from __future__ import annotations

from operator import itemgetter
from typing import TYPE_CHECKING

import duckdb
import numpy as np

from experiments.core_discovery.candidates import ownership

if TYPE_CHECKING:
    from pathlib import Path

    from experiments.core_discovery.data import HeroData


def connect_events(directory: Path, source: Path) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(str(source / "raw/analysis.duckdb"), read_only=True)
    con.execute("SET threads=2")
    con.execute("SET memory_limit='2GB'")
    con.execute(
        "CREATE TEMP TABLE identity_members AS SELECT match_id, player_slot, hero_id, partition FROM read_parquet(?)",
        [str(directory / "observations.parquet")],
    )
    return con


def hero_events(con: duckdb.DuckDBPyConnection, hero: int) -> dict:
    rows = con.execute(
        """
        SELECT p.match_id, p.player_slot, p.item_id, p.buy_time, p.sold_time,
               p.own_net_worth_at_buy, p.state_observed_at_s
        FROM purchases p JOIN identity_members m USING (match_id, player_slot, hero_id)
        WHERE m.hero_id=? AND m.partition='discovery' AND p.buy_time<1200
        ORDER BY p.match_id, p.player_slot, p.buy_time, p.event_order
        """,
        [hero],
    ).fetchall()
    result = {}
    for match, slot, item, bought, sold, wealth, observed in rows:
        player = result.setdefault(int(match), {"slot": int(slot), "items": {}})
        if player["slot"] != slot:
            raise ValueError(
                "A hero/match has multiple players; cannot drop player identity"
            )
        player["items"].setdefault(int(item), []).append((
            bought,
            sold,
            wealth,
            observed,
        ))
    return result


def quantiles(values: list) -> list[float] | None:
    return np.quantile(values, [0.25, 0.50, 0.75]).tolist() if values else None


def action_window(
    events: dict, matches: np.ndarray, completion: np.ndarray, item: int
) -> dict:
    times, wealths = [], []
    for match, completed in zip(matches, completion, strict=True):
        rows = events.get(int(match), {}).get("items", {}).get(item, [])
        eligible = [row for row in rows if row[0] <= completed]
        if not eligible:
            continue
        bought, _, wealth, observed = max(eligible, key=itemgetter(0))
        times.append(bought)
        if wealth is not None and observed is not None and 0 < bought - observed <= 300:
            wealths.append(wealth)
    return {
        "owners_with_purchase": len(times),
        "fresh_wealth_observations": len(wealths),
        "time_seconds_q25_q50_q75": quantiles(times),
        "net_worth_q25_q50_q75": quantiles(wealths),
        "interpretation": "Observed discovery purchases; net worth is not available cash",
    }


def attach_windows(path: dict, data: HeroData, items: list[int], events: dict) -> None:
    index = {item: column for column, item in enumerate(data.items)}
    columns = tuple(index[item] for item in items)
    rows = data.mask("discovery")
    owners = ownership(data.matrix[rows], columns)
    matches = data.matches[rows][owners]
    completion = data.times[rows][owners][:, columns].max(axis=1)
    for action in path["actions"]:
        action["timing"] = action_window(events, matches, completion, action["item_id"])
