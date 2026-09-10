"""Refresh production evidence without model training or comparison reports."""

from __future__ import annotations

import argparse
import os
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from deadlock_build_sync.guide_generator import GENERATOR_NAMES
from deadlock_build_sync.value_validation import integer, require_object_dict

from .api import capture_sources, read_json, write_json
from .beam_snapshot import beam_resume_record, require_beam_resume
from .config import Cohort, RunPaths, parse_timestamp
from .extract import extract_cohort
from .production_evidence import export_production_evidence
from .production_sources import _select_patch_at_timestamp


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--run-id")
    parser.add_argument("--since")
    parser.add_argument("--as-of")
    parser.add_argument("--min-rank", type=int, default=71)
    parser.add_argument("--max-rank", type=int, default=115)
    parser.add_argument("--rank-expansion", choices=("auto", "off"), default="auto")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--generator", choices=GENERATOR_NAMES, default="current")
    args = parser.parse_args(argv)
    if args.workers < 1:
        parser.error("--workers must be at least 1")
    if args.resume and not args.run_id:
        parser.error("--resume requires --run-id")
    state = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))
    paths = RunPaths.create(state / "deadlock-build-sync/offline", args.run_id)
    if args.resume:
        _validate_resume_request(paths, args)
    else:
        _capture_run_sources(paths, args)
    document = export_production_evidence(
        paths,
        args.output,
        workers=args.workers,
        resume=args.resume,
        generator=args.generator,
    )
    print(f"Evidence: {args.output} ({document['artifact_id']})")
    print(f"Source and admission reports: {paths.run}")
    return 0


def _validate_resume_request(paths: RunPaths, args: argparse.Namespace) -> None:
    manifest = require_object_dict(read_json(paths.run / "manifest.json"))
    cohort = require_object_dict(manifest["cohort"])
    if manifest.get("generator", "current") != getattr(args, "generator", "current"):
        raise ValueError("Resume generator must match the source snapshot")
    if manifest.get("generator") == "beam":
        require_beam_resume(manifest)
    if (
        manifest.get("schema_version") != 2
        or manifest.get("production_method") != "eclat_leiden_pairwise"
        or manifest.get("test_usage") != "reserved"
        or not manifest.get("extraction")
        or not (paths.raw / "analysis.duckdb").is_file()
    ):
        raise ValueError("Resume requires a completed production source extraction")
    if (
        manifest.get("rank_expansion") != args.rank_expansion
        or cohort["minimum_badge"] != args.min_rank
        or cohort["maximum_badge"] != args.max_rank
    ):
        raise ValueError("Resume rank options must match the source snapshot")
    for name in ("since", "as_of"):
        requested = getattr(args, name)
        if requested and parse_timestamp(requested) != parse_timestamp(
            str(cohort[name])
        ):
            raise ValueError("Resume time options must match the source snapshot")


def _capture_run_sources(paths: RunPaths, args: argparse.Namespace) -> None:
    if (paths.run / "manifest.json").exists():
        raise ValueError("Use a new --run-id to preserve the previous source snapshot")
    cohort = Cohort(
        minimum_badge=args.min_rank,
        maximum_badge=args.max_rank,
        as_of=parse_timestamp(args.as_of)
        or datetime.now(tz=UTC).replace(microsecond=0),
    )
    sources = capture_sources(paths)
    patch = _select_patch_at_timestamp(paths, cohort.resolved_as_of())
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
    if getattr(args, "generator", "current") != "current":
        manifest["generator"] = args.generator
        manifest["beam_resume"] = beam_resume_record()
    write_json(paths.run / "manifest.json", manifest)
    manifest["extraction"] = extract_cohort(
        paths, cohort, rank_expansion=args.rank_expansion
    )
    write_json(paths.run / "manifest.json", manifest)
