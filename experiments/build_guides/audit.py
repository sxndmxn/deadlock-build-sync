"""Independently replay emitted paths and recount pool buyers from source SQL."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb
from deadlock_build_sync.mechanics import InventoryState, ItemGraph, purchase_item

from experiments.build_guides.paths import covered
from experiments.identity_paths.storage import read_json
from experiments.qdfm.extract import fingerprint


def replay(actions: list[dict], graph: ItemGraph) -> tuple[list[int], int]:
    state, total = InventoryState(), 0
    for action in actions:
        item = action["item_id"]
        if any(part not in state.owned for part in graph.components[item]):
            raise ValueError("An emitted purchase is missing a required component")
        credit = sum(graph.require(part).cost for part in graph.components[item])
        cash = graph.require(item).cost - credit
        if cash != action["incremental_cost"] or credit != action["component_credit"]:
            raise ValueError("Emitted incremental cost or credit is wrong")
        total += cash
        state = purchase_item(graph, state, item)
        if (
            list(state.owned) != action["owned_after"]
            or total != action["cumulative_cost"]
        ):
            raise ValueError("Emitted inventory or cumulative cost is wrong")
    if total != sum(graph.require(item).cost for item in state.owned):
        raise ValueError("Path expenditure disagrees with ending catalog value")
    return list(state.owned), total


def audit_pool(guide: dict) -> None:
    pool = [item for items in guide["item_pool"].values() for item in items]
    if len(pool) != len(set(pool)) or any(
        len(items) > 10 for items in guide["item_pool"].values()
    ):
        raise ValueError("Pool duplicates an item or exceeds a tier limit")
    if set(pool) & {action["item_id"] for action in guide["default_path"]["actions"]}:
        raise ValueError("Pool repeats the default purchase path")
    if set(pool) != {card["item_id"] for card in guide["choices"]}:
        raise ValueError("A pool item is missing its decision card")


def audit_decision(decision: dict, graph: ItemGraph) -> set[int]:
    targets = {option["item_id"] for option in decision["options"]}
    if (decision["kind"] == "pick_one") != (len(targets) > 1):
        raise ValueError("Decision label disagrees with its alternatives")
    represented = set()
    for option in decision["options"]:
        target = option["item_id"]
        if targets & set(graph.transitive_components(target)):
            raise ValueError("An upgrade competes with its component")
        if set(option["route"]) != {target, *graph.transitive_components(target)}:
            raise ValueError("An upgrade route omits a component")
        represented.update(option["choice_items"])
    return represented


def audit_checkpoint(checkpoint: dict, cards: dict, graph: ItemGraph) -> set[int]:
    represented = set()
    for decision in checkpoint["decisions"]:
        represented.update(audit_decision(decision, graph))
    if represented != set(checkpoint["choices"]):
        raise ValueError("A placed choice is missing from its decisions")
    for item in represented:
        card = cards[item]
        if (
            card["branch"] is None
            or card["placement"]["after_step"] != checkpoint["after_step"]
        ):
            raise ValueError("A displayed choice has no executable placement")
    return represented


def audit_decisions(guide: dict, graph: ItemGraph) -> None:
    if guide["schema_version"] != 2:
        raise ValueError("Decision audit requires a version 2 guide")
    cards = {card["item_id"]: card for card in guide["choices"]}
    seen = set()
    for checkpoint in guide["checkpoints"]:
        seen.update(audit_checkpoint(checkpoint, cards, graph))
    unknown, blocked = set(guide["unplaced_choices"]), set(guide["blocked_choices"])
    if (
        seen & (unknown | blocked)
        or unknown & blocked
        or seen | unknown | blocked != set(cards)
    ):
        raise ValueError("Choice status does not cover the pool exactly once")
    for item in unknown:
        card = cards[item]
        if card["placement"]["after_step"] is not None or card["branch"] is not None:
            raise ValueError(
                "Unknown timing was converted into a purchase recommendation"
            )
    for card in cards.values():
        if card["placement"]["supported"] != (
            card["placement"]["after_step"] is not None
        ):
            raise ValueError("Placement support and purchase position disagree")


def audit_guide(guide: dict, graph: ItemGraph) -> int:
    actions = guide["default_path"]["actions"]
    inventory, cost = replay(actions, graph)
    if actions and set(inventory) != set(guide["core_ids"]):
        raise ValueError("Default path does not end in its exact nominated core")
    audit_pool(guide)
    audit_decisions(guide, graph)
    branches = 0
    for card in guide["choices"]:
        if card["purchase_evidence"]["buyers"] < 20:
            raise ValueError("Rare item admitted to the pool")
        if not card["branch"]:
            if not card["blocked_reason"]:
                raise ValueError("A choice is silently missing its path")
            continue
        final, spent = replay(card["branch"]["actions"], graph)
        if (
            final != card["branch"]["final_inventory"]
            or spent != card["branch"]["remaining_cost"]
        ):
            raise ValueError("Branch summary disagrees with its purchases")
        if card["extra_path_cost"] != spent - cost:
            raise ValueError("Branch understates the cost of its detour")
        if not all(covered(graph, item, tuple(final)) for item in guide["core_ids"]):
            raise ValueError("Branch loses the core's upgrade lineages")
        branches += 1
    return branches


def recount(con: duckdb.DuckDBPyConnection, directory: Path, guide: dict) -> int:
    actual = dict(
        con.execute(
            """
        SELECT p.item_id, count(DISTINCT (p.match_id, p.player_slot))
        FROM purchases p JOIN read_parquet(?) o USING(match_id, player_slot, hero_id)
        WHERE o.partition='discovery' AND o.hero_id=?
          AND list_has_all(o.current_items, ?) AND p.buy_time <= p.duration_s
        GROUP BY p.item_id
        """,
            [
                str(directory / "observations.parquet"),
                guide["hero_id"],
                guide["core_ids"],
            ],
        ).fetchall()
    )
    for card in guide["choices"]:
        if actual.get(card["item_id"], 0) != card["purchase_evidence"]["buyers"]:
            raise ValueError("Independent SQL buyer count disagrees with a pool card")
    return len(guide["choices"])


def compare_baseline(guides: list[dict], baseline: Path) -> None:
    manifest = read_json(baseline / "manifest.json")
    for name, expected in manifest["files"].items():
        if fingerprint(baseline / name) != expected:
            raise ValueError("Baseline artifact changed before comparison")
    previous = {
        row["identity_id"]: row
        for name in manifest["files"]
        if name.endswith(".json")
        for row in [read_json(baseline / name)]
    }
    if set(previous) != {guide["identity_id"] for guide in guides}:
        raise ValueError("The identity set changed from the baseline")
    fields = (
        "core_ids",
        "core_validation",
        "passes_core_gate",
        "passes_identity_gate",
        "passes_sequence_gate",
        "core_path_supported",
        "full_policy_validated",
        "default_path",
        "item_pool",
    )
    for guide in guides:
        if any(guide[key] != previous[guide["identity_id"]][key] for key in fields):
            raise ValueError("Frozen core, evidence, default path or pool changed")


def run(directory: Path, baseline: Path | None = None) -> dict:
    manifest = read_json(directory / "manifest.json")
    for name, expected in manifest["files"].items():
        if fingerprint(directory / name) != expected:
            raise ValueError("Generated artifact changed before audit")
    guides = [
        read_json(directory / name)
        for name in manifest["files"]
        if name.endswith(".json")
    ]
    if baseline is not None:
        compare_baseline(guides, baseline)
    frozen = read_json(Path(manifest["identity_run"]) / "manifest.json")
    data = Path(frozen["directory"])
    source = Path(read_json(data / "manifest.json")["source"])
    graph = ItemGraph.from_assets(read_json(source / "raw/items.json"))
    con = duckdb.connect(str(source / "raw/analysis.duckdb"), read_only=True)
    con.execute("SET threads=2")
    branches, buyers = 0, 0
    try:
        for guide in guides:
            if (
                fingerprint(Path(guide["catalog_source"]["path"]))
                != guide["catalog_source"]["sha256"]
            ):
                raise ValueError("Item catalog changed before audit")
            branches += audit_guide(guide, graph)
            buyers += recount(con, data, guide)
    finally:
        con.close()
    report = {
        "guides": len(guides),
        "legal_branches_replayed": branches,
        "pool_counts_verified": buyers,
        "unplaced_choices": sum(len(guide["unplaced_choices"]) for guide in guides),
        "blocked_choices": sum(len(guide["blocked_choices"]) for guide in guides),
        "baseline_preserved": baseline is not None,
        "failures": 0,
    }
    (directory / "audit.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--baseline", type=Path)
    args = parser.parse_args()
    print(json.dumps(run(args.directory, args.baseline), indent=2))
