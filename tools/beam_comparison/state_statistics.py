"""Measure current default cores in the same wealth states as beam cores."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from deadlock_build_sync.artifacts import atomic_write_json
from deadlock_build_sync.offline import discovery_export, production_evidence
from deadlock_build_sync.offline.beam_nomination import core_items
from deadlock_build_sync.offline.beam_support import core_state_statistics
from deadlock_build_sync.offline.config import RunPaths
from deadlock_build_sync.offline.discovery_data import (
    load_hero_discovery_data,
    prepare_discovery_partitions,
)
from deadlock_build_sync.value_validation import (
    integer,
    require_object_dict,
    require_object_rows,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    source = args.root / "source/results/master-0ecad50"
    paths = RunPaths(
        source.parent.parent,
        source,
        source / "raw",
        source / "data",
        source / "tables",
        source / "figures",
        source / "raw/api",
    )
    manifest = require_object_dict(
        json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    )
    # Use the producer's exact source and database configuration.
    context = production_evidence._export_context(  # ruff: ignore[private-member-access]
        paths, require_object_dict(manifest["cohort"]), manifest
    )
    document = require_object_dict(
        json.loads(
            (args.root / "current/build-evidence.json").read_text(encoding="utf-8")
        )
    )
    result: dict[str, object] = {}
    for hero in require_object_rows(document["heroes"]):
        cohort = require_object_dict(hero["cohort"])
        # This connection reads captured matches and creates temporary relations.
        with discovery_export._open_discovery_database(context) as connection:  # ruff: ignore[private-member-access]
            prepare_discovery_partitions(connection)
            values = load_hero_discovery_data(
                connection,
                integer(hero["hero_id"]),
                context.item_graph,
                integer(cohort["minimum_badge"]),
                integer(cohort["maximum_badge"]),
            )
            for build in require_object_rows(hero["builds"]):
                if build["path_id"] == build["guide_group_id"]:
                    result[str(build["path_id"])] = {
                        str(state): core_state_statistics(
                            values, tuple(sorted(core_items(build))), state
                        )
                        for state in range(3)
                    }
    atomic_write_json(args.root / "current-state-statistics.json", result)


if __name__ == "__main__":
    main()
