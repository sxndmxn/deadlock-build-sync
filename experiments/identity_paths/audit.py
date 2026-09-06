"""Independent SQL, original-event replay and arithmetic checks of a trial."""

from __future__ import annotations

import argparse
from itertools import pairwise
from pathlib import Path

import duckdb
import numpy as np
from deadlock_build_sync.mechanics import BASE_INVENTORY_SLOTS, MAX_ACTIVE_ITEMS

from experiments.core_discovery.data import write_json
from experiments.identity_paths.storage import read_json, verify_run
from experiments.qdfm.extract import fingerprint
from experiments.qdfm.state import Catalog


def sql_core(con: duckdb.DuckDBPyConnection, row: dict) -> tuple:
    return con.execute(
        """
        SELECT count(*), coalesce(sum(won::INTEGER),0)
        FROM audit_observations WHERE hero_id=? AND partition='validation'
        AND list_has_all(current_items, ?)
        """,
        [row["hero_id"], row["items"]],
    ).fetchone()


def sql_adjustment(con: duckdb.DuckDBPyConnection, row: dict) -> float | None:
    cells = con.execute(
        """
        SELECT floor(wealth/5000),
               CASE WHEN team_lead_share < -.10 THEN 0 WHEN team_lead_share < -.03 THEN 1
                    WHEN team_lead_share < .03 THEN 2 WHEN team_lead_share < .10 THEN 3 ELSE 4 END,
               floor(average_badge/20), list_has_all(current_items, ?) AS owned,
               count(*), sum(won::INTEGER)
        FROM audit_observations WHERE hero_id=? AND partition='validation'
        GROUP BY 1,2,3,4
        """,
        [row["items"], row["hero_id"]],
    ).fetchall()
    strata = {}
    for wealth, lead, badge, owned, count, wins in cells:
        strata.setdefault((wealth, lead, badge), {})[bool(owned)] = (count, wins)
    shared = [
        value
        for value in strata.values()
        if len(value) == 2 and min(value[False][0], value[True][0]) >= 10
    ]
    total = sum(value[True][0] for value in shared)
    if total < 100:
        return None
    return sum(
        value[True][0]
        / total
        * (value[True][1] / value[True][0] - value[False][1] / value[False][0])
        for value in shared
    )


def check_paths(
    previews: list[dict], catalog: Catalog, assets: list[dict]
) -> tuple[int, list]:
    by_id = {row["id"]: row for row in assets}
    errors, checked = [], set()
    for row in previews:
        path = row["path"]
        key = (row["identity_id"], path["method"])
        if not path["legal"] or key in checked:
            continue
        checked.add(key)
        owned, spent = set(), 0
        for action in path["actions"]:
            item = action["item_id"]
            components = set(catalog.components[item]) & owned
            credit = sum(catalog.costs[component] for component in components)
            cash = catalog.costs[item] - credit
            duplicate = item in owned
            owned -= components
            owned.add(item)
            spent += cash
            valid = (
                not duplicate
                and len(owned) <= BASE_INVENTORY_SLOTS
                and sum(bool(by_id[value].get("is_active_item")) for value in owned)
                <= MAX_ACTIVE_ITEMS
                and credit == action["component_credit"]
                and cash == action["incremental_cost"]
                and spent == action["cumulative_cost"]
                and owned == set(action["owned_after"])
            )
            if not valid:
                errors.append({"path": key, "item": item})
        if owned != set(row["items"]) or spent != row["cost"]:
            errors.append({"path": key, "error": "final inventory/cost"})
    return len(checked), errors


def check_orders(
    con: duckdb.DuckDBPyConnection, previews: list[dict]
) -> tuple[int, list]:
    checked, errors = set(), []
    for row in previews:
        order = row["path"]["order"]
        key = (row["identity_id"], tuple(order))
        if not order or key in checked:
            continue
        checked.add(key)
        owners = con.execute(
            "SELECT current_items, acquired_times FROM audit_observations WHERE hero_id=? AND partition='validation' AND list_has_all(current_items, ?)",
            [row["hero_id"], row["items"]],
        ).fetchall()
        count = 0
        for items, times in owners:
            acquired = dict(zip(items, times, strict=True))
            ordered = [acquired[item] for item in order]
            count += all(first < second for first, second in pairwise(ordered))
        if count != row["order_validation"]["ordered_owners"]:
            errors.append({"key": key, "actual": count})
    return len(checked), errors


def replay_sample(con: duckdb.DuckDBPyConnection, catalog: Catalog) -> tuple[int, list]:
    rows = con.execute(
        """
        SELECT match_id, player_slot, current_items, acquired_times
        FROM audit_observations
        QUALIFY row_number() OVER (PARTITION BY hero_id, partition ORDER BY hash(match_id, player_slot)) <= 5
        """
    ).fetchall()
    errors = []
    for match, slot, expected, acquired in rows:
        events = con.execute(
            "SELECT item_id, buy_time, sold_time FROM purchases WHERE match_id=? AND player_slot=? AND buy_time<1200 ORDER BY buy_time,event_order",
            [match, slot],
        ).fetchall()
        purchases = catalog.purchases(
            *([event[column] for event in events] for column in range(3))
        )
        inventory = catalog.inventory(purchases, 1200)
        latest = {event.item: event.time for event in purchases}
        timing = [latest[item] for item in expected]
        if set(inventory) != set(expected) or timing != acquired:
            errors.append({"match": match, "slot": slot})
    return len(rows), errors


def run(runs: Path) -> None:
    manifest, _ = verify_run(runs)
    evaluation = read_json(runs / "evaluation.json")
    directory = Path(manifest["directory"])
    source = Path(read_json(directory / "manifest.json")["source"])
    con = duckdb.connect(str(source / "raw/analysis.duckdb"), read_only=True)
    con.execute(
        "CREATE TEMP TABLE audit_observations AS SELECT * FROM read_parquet(?)",
        [str(directory / "observations.parquet")],
    )
    errors = []
    for identity, row in evaluation["cores"].items():
        count, wins = sql_core(con, row)
        adjusted = sql_adjustment(con, row)
        expected = row["validation"]["adjusted"]["difference"]
        adjustment_matches = (adjusted is None and expected is None) or (
            adjusted is not None
            and expected is not None
            and np.isclose(adjusted, expected, atol=1e-12)
        )
        if (
            count != row["validation"]["owners"]
            or wins != row["validation"]["wins"]
            or not adjustment_matches
        ):
            errors.append(identity)
    catalog = Catalog(source)
    path_count, path_errors = check_paths(
        evaluation["previews"], catalog, read_json(source / "raw/items.json")
    )
    order_count, order_errors = check_orders(con, evaluation["previews"])
    samples, replay_errors = replay_sample(con, catalog)
    cross_partition = con.execute(
        "SELECT count(*) FROM (SELECT match_id FROM audit_observations GROUP BY match_id HAVING count(DISTINCT partition)>1)"
    ).fetchone()[0]
    con.close()
    report = {
        "evaluation_sha256": fingerprint(runs / "evaluation.json"),
        "audit_source_sha256": fingerprint(Path(__file__)),
        "core_sql_checks": len(evaluation["cores"]),
        "core_sql_errors": errors,
        "path_checks": path_count,
        "path_errors": path_errors,
        "order_checks": order_count,
        "order_errors": order_errors,
        "original_inventory_replays": samples,
        "replay_errors": replay_errors,
        "cross_partition_matches": cross_partition,
    }
    write_json(runs / "audit.json", report)
    if errors or path_errors or order_errors or replay_errors or cross_partition:
        raise ValueError("Independent audit failed; see audit.json")
    print(report, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=Path, required=True)
    run(parser.parse_args().runs)
