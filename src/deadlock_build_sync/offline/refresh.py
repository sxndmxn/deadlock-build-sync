"""Refresh production evidence without model training or comparison reports."""

from __future__ import annotations

import argparse
import os
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from deadlock_build_sync.value_validation import integer

from .api import capture_sources, write_json
from .config import Cohort, RunPaths, parse_timestamp
from .extract import extract_cohort
from .production_evidence import export_production_evidence
from .production_sources import _patch_at


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--run-id")
    parser.add_argument("--since")
    parser.add_argument("--as-of")
    parser.add_argument("--min-rank", type=int, default=71)
    parser.add_argument("--max-rank", type=int, default=115)
    parser.add_argument("--rank-expansion", choices=("auto", "off"), default="auto")
    args = parser.parse_args(argv)
    state = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))
    paths = RunPaths.create(state / "deadlock-build-sync/offline", args.run_id)
    if (paths.run / "manifest.json").exists():
        raise ValueError("Use a new --run-id to preserve the previous source snapshot")
    cohort = Cohort(
        minimum_badge=args.min_rank,
        maximum_badge=args.max_rank,
        as_of=parse_timestamp(args.as_of)
        or datetime.now(tz=UTC).replace(microsecond=0),
    )
    sources = capture_sources(paths)
    patch = _patch_at(paths, cohort.resolved_as_of())
    patch_start = datetime.fromtimestamp(integer(patch["start_timestamp"]), UTC)
    requested = parse_timestamp(args.since) or cohort.since
    cohort = replace(cohort, since=max(requested, patch_start))
    cohort.validate()
    manifest = {
        "schema_version": 2,
        "rank_expansion": args.rank_expansion,
        "cohort": cohort.as_dict(),
        "sources": sources,
        "production_method": "eclat_leiden_pairwise",
        "test_usage": "reserved",
    }
    write_json(paths.run / "manifest.json", manifest)
    manifest["extraction"] = extract_cohort(
        paths, cohort, rank_expansion=args.rank_expansion
    )
    write_json(paths.run / "manifest.json", manifest)
    document = export_production_evidence(paths, args.output)
    print(f"Evidence: {args.output} ({document['artifact_id']})")
    print(f"Source and admission reports: {paths.run}")
    return 0
