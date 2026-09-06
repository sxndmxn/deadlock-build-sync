"""Reproduce the three-arm comparison on planted winning and losing cores."""

from __future__ import annotations

import argparse
from pathlib import Path

from tools.comparisons.core_discovery.data import write_json
from tools.comparisons.identity_paths.config import ARMS
from tools.comparisons.identity_paths.evaluate import validate_core, validate_path
from tools.comparisons.identity_paths.fit import discover_hero, nominate
from tools.comparisons.identity_paths.storage import producer_hashes
from tools.comparisons.identity_paths.test_identity_paths import (
    catalog_fixture,
    graph_fixture,
    planted_data,
)
from tools.comparisons.qdfm.extract import fingerprint


def run(output: Path) -> None:
    output.mkdir(parents=True, exist_ok=False)
    data = planted_data(seed=123, per_fold=3000)
    catalog = catalog_fixture(13)
    fit = discover_hero(data, catalog)
    assets = [
        {
            "id": 99,
            "class_name": "ability",
            "name": "Synthetic melee ability",
            "description": "Heavy melee damage",
        }
    ]
    assets.extend(
        {
            "id": item,
            "name": f"Synthetic item {item}",
            "description": "Heavy melee damage",
        }
        for item in range(13)
    )
    rows = nominate(
        fit, data, {"items": {"signature1": "ability"}}, assets, graph_fixture(13), {}
    )
    unique = {row["identity_id"]: row for row in rows}
    validation = {
        identity: validate_core(row, data, len(unique), catalog)
        for identity, row in unique.items()
    }
    previews = [
        validate_path(row, data, validation[row["identity_id"]]) for row in rows
    ]
    summaries = {}
    for arm in ARMS:
        chosen = [row for row in previews if row["arm"] == arm]
        summaries[arm] = {
            "nominated": len(chosen),
            "planted_losing_core_nominated": any(
                {8, 9, 10, 11} <= set(row["items"]) for row in chosen
            ),
            "validated_cores": sum(row["passes_core_gate"] for row in chosen),
            "complete_previews": sum(row["complete_preview"] for row in chosen),
            "winning_groups_represented": sorted({
                group
                for group in range(2)
                for row in chosen
                if set(range(4 * group, 4 * group + 4)) <= set(row["items"])
            }),
        }
    write_json(
        output / "report.json",
        {
            "seed": 123,
            "observations": len(data.won),
            "per_fold": 3000,
            "group_win_probabilities": [0.75, 0.65, 0.25],
            "summaries": summaries,
            "fit": fit,
            "previews": previews,
            "producer_sha256": producer_hashes(),
            "synthetic_source_sha256": {
                name: fingerprint(Path(__file__).parent / name)
                for name in ("synthetic.py", "test_identity_paths.py")
            },
            "interpretation": "Planted association/recovery check, not a Deadlock simulator",
        },
    )
    print(summaries, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args().output)
