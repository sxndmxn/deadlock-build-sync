"""Replay serialized routes and check action coverage in all price tiers."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from deadlock_build_sync.artifacts import atomic_write_json
from deadlock_build_sync.mechanics import ItemGraph, MechanicsError
from deadlock_build_sync.purchase_planner import plan_purchases
from deadlock_build_sync.value_validation import (
    integer,
    require_object_dict,
    require_object_list,
    require_object_rows,
)


def replay_variant(variant: dict[str, object], graph: ItemGraph) -> dict[str, object]:
    guidance = require_object_dict(variant["purchase_guidance"])
    actions = require_object_rows(
        require_object_dict(guidance["default_path"])["actions"]
    )
    path = tuple(integer(action["item_id"]) for action in actions)
    core = tuple(integer(item) for item in require_object_list(variant["core"]))
    failures = []
    try:
        plan = plan_purchases(graph, path, core, {})
    except (MechanicsError, ValueError) as error:
        failures.append(str(error))
    else:
        if tuple(action.item_id for action in plan.actions) != path:
            failures.append("Replay changes the serialized purchase path")
        if set(plan.final_inventory) != set(core):
            failures.append("Final inventory differs from the declared core")
        if plan.remaining_cost != variant["core_cost"]:
            failures.append("Purchase cost differs from the declared core cost")
    pools = require_object_dict(variant["item_pool"])
    missing = [
        tier
        for tier in range(1, 5)
        if not pools[str(tier)]
        and not any(graph.require(item).tier == tier for item in path)
    ]
    return {
        "path_id": variant["path_id"],
        "mechanical_failures": failures,
        "missing_tier_coverage": missing,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    root = args.root
    assets = require_object_rows(
        json.loads(
            (root / "source/results/master-0ecad50/raw/items-all.json").read_text(
                encoding="utf-8"
            )
        )
    )
    graph = ItemGraph.from_assets(assets)
    for mode in ("current", "beam-order", "beam"):
        index = require_object_dict(
            json.loads((root / mode / "builds.json").read_text(encoding="utf-8"))
        )
        document = require_object_dict(
            json.loads(
                (Path(str(index["directory"])) / "guides.json").read_text(
                    encoding="utf-8"
                )
            )
        )
        rows = [
            replay_variant(variant, graph)
            for guide in require_object_rows(document["guides"])
            for variant in require_object_rows(
                require_object_dict(guide["guide_group"])["variants"]
            )
        ]
        atomic_write_json(
            root / mode / "independent-replay.json",
            {
                "checked_variants": len(rows),
                "mechanical_failures": [
                    row for row in rows if row["mechanical_failures"]
                ],
                "missing_tier_coverage": [
                    row for row in rows if row["missing_tier_coverage"]
                ],
            },
        )


if __name__ == "__main__":
    main()
