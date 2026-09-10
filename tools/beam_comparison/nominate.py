"""Compare beam core selection and beam ordering against a saved master baseline."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from deadlock_build_sync.artifacts import atomic_write_json
from deadlock_build_sync.guide_generator import (
    BEAM_METHOD_VERSION,
    BEAM_SCHEMA_VERSION,
    generator_record,
)
from deadlock_build_sync.offline import production_evidence
from deadlock_build_sync.offline.beam_export import generate_beam_roster
from deadlock_build_sync.offline.config import RunPaths
from deadlock_build_sync.offline.production_storage import write_validated_evidence
from deadlock_build_sync.snapshot import sha256_json
from deadlock_build_sync.value_validation import (
    require_object_dict,
    require_object_rows,
)
from tools.beam_comparison.revalidate import RevalidationOptions, revalidate_roster


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--mode", choices=("beam", "beam-order"), required=True)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--frozen", type=Path)
    args = parser.parse_args()
    root, mode = args.root, args.mode
    source = root / "source/results/master-0ecad50"
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
    # Reuse the producer's captured catalog and rank configuration.
    context = production_evidence._export_context(  # ruff: ignore[private-member-access]
        paths, require_object_dict(manifest["cohort"]), manifest
    )
    heroes = require_object_rows(
        json.loads((source / "raw/heroes.json").read_text(encoding="utf-8"))
    )
    baseline = require_object_dict(
        json.loads((root / "current/build-evidence.json").read_text(encoding="utf-8"))
    )
    started = time.monotonic()
    parameters = {"workers": args.workers, "order_only": mode == "beam-order"}
    if args.frozen:
        baseline["heroes"] = revalidate_roster(
            args.frozen,
            heroes,
            require_object_rows(baseline["heroes"]),
            context,
            options=RevalidationOptions(args.workers, mode == "beam-order"),
        )
    else:
        baseline["heroes"] = generate_beam_roster(
            heroes, require_object_rows(baseline["heroes"]), context, **parameters
        )
    baseline.pop("artifact_id")
    baseline["generator"] = generator_record()
    baseline["schema_version"] = BEAM_SCHEMA_VERSION
    require_object_dict(baseline["method"])["version"] = BEAM_METHOD_VERSION
    require_object_dict(baseline["method"])["core_selection"] = (
        "Frozen groups with state-aware beam search and complete guide admission"
    )
    baseline["artifact_id"] = sha256_json(baseline)
    output = root / mode / "build-evidence.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    write_validated_evidence(output, baseline)
    atomic_write_json(
        root / f"{mode}-run.json",
        {
            "artifact_id": baseline["artifact_id"],
            "workers": args.workers,
            "elapsed_seconds": time.monotonic() - started,
            "source": str(source),
            "frozen_revalidation": str(args.frozen) if args.frozen else None,
        },
    )
    sys.stdout.write(f"Complete {mode} evidence: {output}\n")


if __name__ == "__main__":
    main()
