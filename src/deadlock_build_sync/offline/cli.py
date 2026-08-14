from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .analysis import analyze
from .api import capture_api_audit, capture_sources, read_json, write_json
from .config import Cohort, RunPaths, parse_timestamp
from .extract import extract_cohort
from .layout import write_build_layout
from .production_evidence import export_production_evidence
from .rankings import generate_rankings
from .report import render_report
from .xgb_ranker import ExperimentConfig, run_xgboost_experiment

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
_SOURCE_CHECKOUT = Path(__file__).resolve().parents[3]
PRODUCTION_REPO = (
    _SOURCE_CHECKOUT
    if (_SOURCE_CHECKOUT / "pyproject.toml").is_file()
    else PACKAGE_ROOT
)
_STATE_HOME = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))
PROJECT_ROOT = _STATE_HOME / "deadlock-build-sync/offline"
MAX_CACHE_BYTES = 8 * 1024**3


def _repo_identity() -> dict[str, str]:
    if PRODUCTION_REPO == PACKAGE_ROOT:
        digest = hashlib.sha256()
        for path in sorted(PACKAGE_ROOT.rglob("*.py")):
            digest.update(str(path.relative_to(PACKAGE_ROOT)).encode())
            digest.update(path.read_bytes())
        return {
            "status": "installed-package",
            "tracked_index_sha256": digest.hexdigest(),
        }
    git = shutil.which("git")
    if git is None:
        raise RuntimeError("git is required to record the producer source identity")
    status = subprocess.run(
        [git, "status", "--short", "--branch"],
        cwd=PRODUCTION_REPO,
        check=True,
        capture_output=True,
        shell=False,
        text=True,
    ).stdout
    index = subprocess.run(
        [git, "ls-files", "-s"],
        cwd=PRODUCTION_REPO,
        check=True,
        capture_output=True,
        shell=False,
    ).stdout
    return {
        "status": status.strip(),
        "tracked_index_sha256": hashlib.sha256(index).hexdigest(),
    }


def _manifest(paths: RunPaths, cohort: Cohort) -> dict[str, Any]:
    target = paths.run / "manifest.json"
    if target.exists():
        return read_json(target)
    return {
        "schema_version": 1,
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "cohort": cohort.as_dict(),
        "run_id": paths.run.name,
        "project_root": str(paths.root),
        "producer_source": str(PRODUCTION_REPO),
    }


def _cohort_from_manifest(manifest: dict[str, Any]) -> Cohort:
    value = manifest.get("cohort")
    if not isinstance(value, dict):
        raise SystemExit("existing run manifest has no valid frozen cohort")
    since = parse_timestamp(str(value["since"]))
    as_of = parse_timestamp(str(value["as_of"]))
    if since is None or as_of is None:
        raise SystemExit("existing run manifest has incomplete cohort timestamps")
    cohort = Cohort(
        minimum_badge=int(value["minimum_badge"]),
        maximum_badge=int(value["maximum_badge"]),
        since=since,
        as_of=as_of,
        match_mode=str(value.get("match_mode") or "Ranked"),
        game_mode=str(value.get("game_mode") or "Normal"),
    )
    cohort.validate()
    return cohort


def _check_explicit_cohort_args(args: argparse.Namespace, frozen: Cohort) -> None:
    comparisons = (
        ("--min-rank", args.min_rank, frozen.minimum_badge),
        ("--max-rank", args.max_rank, frozen.maximum_badge),
        ("--since", parse_timestamp(args.since), frozen.since),
        ("--as-of", parse_timestamp(args.as_of), frozen.resolved_as_of()),
    )
    conflicts = [
        name
        for name, requested, stored in comparisons
        if requested is not None and requested != stored
    ]
    if conflicts:
        raise SystemExit(
            "existing run has a different frozen cohort; use a new --run-id "
            f"instead of changing {', '.join(conflicts)}"
        )


def _save_manifest(paths: RunPaths, manifest: dict[str, Any]) -> None:
    write_json(paths.run / "manifest.json", manifest)


def _cache_size(paths: RunPaths) -> int:
    return sum(path.stat().st_size for path in paths.run.rglob("*") if path.is_file())


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _frozen_data_hashes(paths: RunPaths) -> dict[str, str]:
    return {
        str(path.relative_to(paths.run)): _file_sha256(path)
        for path in sorted(paths.data.glob("*.parquet"))
    }


def _require(paths: RunPaths, *relative: str) -> None:
    missing = [value for value in relative if not (paths.run / value).exists()]
    if missing:
        raise SystemExit(
            f"run {paths.run.name} is missing prerequisites: {', '.join(missing)}"
        )


def run_extract(paths: RunPaths, cohort: Cohort, manifest: dict[str, Any]) -> None:
    manifest["sources"] = capture_sources(paths)
    manifest["extraction"] = extract_cohort(paths, cohort)
    manifest["cache_bytes"] = _cache_size(paths)
    _save_manifest(paths, manifest)


def run_audit(paths: RunPaths, cohort: Cohort, manifest: dict[str, Any]) -> None:
    _require(paths, "raw/heroes.json")
    manifest["api_audit"] = capture_api_audit(paths, cohort)
    _save_manifest(paths, manifest)


def run_analysis(paths: RunPaths, manifest: dict[str, Any]) -> None:
    _require(paths, "raw/analysis.duckdb", "raw/api")
    manifest["analysis"] = analyze(paths)
    manifest["rankings"] = generate_rankings(paths)
    manifest["cache_bytes"] = _cache_size(paths)
    if manifest["cache_bytes"] > MAX_CACHE_BYTES:
        raise RuntimeError(
            f"run cache is {manifest['cache_bytes'] / 1024**3:.1f} GiB; 8 GiB cap exceeded"
        )
    _save_manifest(paths, manifest)


def run_report(paths: RunPaths, manifest: dict[str, Any]) -> None:
    _require(paths, "tables/item_metrics.csv", "tables/top10_rankings.csv")
    manifest["frozen_data_sha256"] = _frozen_data_hashes(paths)
    _save_manifest(paths, manifest)
    manifest["reporting"] = render_report(paths)
    _save_manifest(paths, manifest)


def run_layout(
    paths: RunPaths,
    manifest: dict[str, Any],
    *,
    hero_id: int,
    hero_name: str,
    minimum_net_worth: int,
) -> None:
    stem = f"late_game_hero_{hero_id}_{minimum_net_worth}"
    _require(paths, f"tables/{stem}.json", f"tables/{stem}_items.csv")
    json_path, markdown_path = write_build_layout(
        paths,
        hero_id=hero_id,
        hero_name=hero_name,
        minimum_net_worth=minimum_net_worth,
    )
    manifest["build_layout"] = {
        "hero_id": hero_id,
        "hero": hero_name,
        "minimum_net_worth": minimum_net_worth,
        "json": str(json_path.relative_to(paths.run)),
        "markdown": str(markdown_path.relative_to(paths.run)),
    }
    _save_manifest(paths, manifest)


def run_xgboost(
    paths: RunPaths, manifest: dict[str, Any], *, config: ExperimentConfig
) -> None:
    _require(
        paths,
        "raw/analysis.duckdb",
        "raw/heroes.json",
        "raw/items.json",
    )
    manifest["xgboost"] = run_xgboost_experiment(paths, config)
    _save_manifest(paths, manifest)


def run_export_evidence(paths: RunPaths, output: Path) -> None:
    _require(
        paths,
        "manifest.json",
        "raw/analysis.duckdb",
        "raw/heroes.json",
        "raw/items.json",
        "raw/items-all.json",
        "raw/patches.json",
        "raw/ranks.json",
        "tables/item_metrics.csv",
    )
    document = export_production_evidence(paths, output)
    print(
        f"Exported {len(document['heroes'])} heroes of production evidence: {output}",
        flush=True,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="deadlock-build-sync refresh-evidence",
        description="Run the read-only Deadlock evidence producer.",
    )
    parser.add_argument(
        "command",
        choices=(
            "extract",
            "audit",
            "analyze",
            "report",
            "layout",
            "xgboost",
            "export-evidence",
            "all",
        ),
    )
    parser.add_argument("--run-id", help="stable result directory identifier")
    parser.add_argument("--min-rank", type=int)
    parser.add_argument("--max-rank", type=int)
    parser.add_argument("--since")
    parser.add_argument(
        "--as-of", help="frozen upper timestamp; defaults to command start"
    )
    parser.add_argument("--hero-id", type=int, help="hero identifier for layout")
    parser.add_argument("--hero-name", help="hero display name for layout")
    parser.add_argument(
        "--minimum-net-worth",
        type=int,
        default=45_000,
        help="late-game final-net-worth threshold for layout",
    )
    parser.add_argument("--xgb-train-queries", type=int, default=20_000)
    parser.add_argument("--xgb-validation-queries", type=int, default=5_000)
    parser.add_argument("--xgb-test-queries", type=int, default=10_000)
    parser.add_argument("--xgb-pilot-train-queries", type=int, default=8_000)
    parser.add_argument("--xgb-pilot-validation-queries", type=int, default=2_000)
    parser.add_argument("--xgb-bootstrap-replicates", type=int, default=1_000)
    parser.add_argument(
        "--output",
        type=Path,
        help="output path required by export-evidence",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    defaults = Cohort()
    cohort = Cohort(
        minimum_badge=args.min_rank or defaults.minimum_badge,
        maximum_badge=args.max_rank or defaults.maximum_badge,
        since=parse_timestamp(args.since) or defaults.since,
        as_of=parse_timestamp(args.as_of)
        or datetime.now(tz=UTC).replace(microsecond=0),
    )
    cohort.validate()
    paths = RunPaths.create(PROJECT_ROOT, args.run_id)
    existing_run = (paths.run / "manifest.json").exists()
    manifest = _manifest(paths, cohort)
    if existing_run:
        frozen_cohort = _cohort_from_manifest(manifest)
        _check_explicit_cohort_args(args, frozen_cohort)
        cohort = frozen_cohort
    before = _repo_identity()
    manifest["producer_source_before"] = before
    _save_manifest(paths, manifest)

    if args.command in {"extract", "all"}:
        run_extract(paths, cohort, manifest)
    if args.command in {"audit", "all"}:
        run_audit(paths, cohort, manifest)
    if args.command in {"analyze", "all"}:
        run_analysis(paths, manifest)
    if args.command == "layout":
        if args.hero_id is None or not args.hero_name:
            raise SystemExit("layout requires --hero-id and --hero-name")
        run_layout(
            paths,
            manifest,
            hero_id=args.hero_id,
            hero_name=args.hero_name,
            minimum_net_worth=args.minimum_net_worth,
        )
    if args.command in {"xgboost", "all"}:
        limits = (
            args.xgb_train_queries,
            args.xgb_validation_queries,
            args.xgb_test_queries,
            args.xgb_pilot_train_queries,
            args.xgb_pilot_validation_queries,
            args.xgb_bootstrap_replicates,
        )
        if any(value <= 0 for value in limits):
            raise SystemExit("all XGBoost query and bootstrap limits must be positive")
        run_xgboost(
            paths,
            manifest,
            config=ExperimentConfig(
                train_queries=args.xgb_train_queries,
                validation_queries=args.xgb_validation_queries,
                test_queries=args.xgb_test_queries,
                pilot_train_queries=args.xgb_pilot_train_queries,
                pilot_validation_queries=args.xgb_pilot_validation_queries,
                bootstrap_replicates=args.xgb_bootstrap_replicates,
            ),
        )
    if args.command in {"report", "all"}:
        run_report(paths, manifest)
    if args.command in {"export-evidence", "all"}:
        if args.output is None:
            raise SystemExit(f"{args.command} requires --output")
        run_export_evidence(paths, args.output.expanduser().resolve())

    after = _repo_identity()
    manifest["producer_source_after"] = after
    manifest["producer_source_unchanged"] = before == after
    manifest["completed_at"] = datetime.now(tz=UTC).isoformat()
    _save_manifest(paths, manifest)
    if before != after:
        raise RuntimeError("producer source identity changed during isolated analysis")
    print(json.dumps({"run": str(paths.run), "manifest": manifest}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
