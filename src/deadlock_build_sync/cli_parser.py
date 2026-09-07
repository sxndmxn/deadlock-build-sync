from __future__ import annotations

import argparse
import os
from pathlib import Path

from .api import DEFAULT_API_BASE_URL
from .ranks import DEFAULT_RANK_RANGE, Rank
from .snapshot import EpochBoundary, MatchMode
from .tracing import TRACE_ENVIRONMENT_VARIABLE, TraceError, TraceMode

DEFAULT_NARRATIVE_PATH = Path("generated/narratives.json")


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def _trace_mode(value: str) -> TraceMode:
    try:
        return TraceMode.parse(value)
    except TraceError as error:
        raise argparse.ArgumentTypeError(str(error)) from error


def _trace_argument(
    parser: argparse.ArgumentParser,
    *,
    default: TraceMode | str | None,
) -> None:
    parser.add_argument(
        "--trace",
        type=_trace_mode,
        choices=tuple(TraceMode),
        default=default,
        metavar="{stages,calls}",
        help=(
            "write a value-free execution trace "
            f"(environment: {TRACE_ENVIRONMENT_VARIABLE})"
        ),
    )


def _common_location_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--account-id", type=int, help="Steam account ID3; auto-detected by default"
    )
    parser.add_argument(
        "--cache-path", type=Path, help="override cached_hero_builds.kv3 path"
    )


def _hero_arguments(parser: argparse.ArgumentParser) -> None:
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--hero", help="active hero name, class name, or numeric ID")
    selection.add_argument(
        "--all",
        action="store_true",
        help="generate every active hero with reliable analytics",
    )


def _narrative_argument(parser: argparse.ArgumentParser) -> None:
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument(
        "--narratives",
        type=Path,
        help=(
            "reviewed deterministic description artifact from export-context "
            f"(default: {DEFAULT_NARRATIVE_PATH})"
        ),
    )
    selection.add_argument(
        "--without-narratives",
        action="store_const",
        const=None,
        dest="narratives",
        help="generate analytics-only guides with empty narrative fields",
    )
    parser.set_defaults(narratives=DEFAULT_NARRATIVE_PATH)


def _rank_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--rank-expansion",
        choices=("auto", "off"),
        default="auto",
        help="expand each hero only when build support is insufficient",
    )
    parser.add_argument(
        "--min-rank",
        type=Rank.parse,
        default=DEFAULT_RANK_RANGE.minimum,
        metavar="TIER-DIVISION",
        help=f"lowest average rank (default: {DEFAULT_RANK_RANGE.minimum.slug})",
    )
    parser.add_argument(
        "--max-rank",
        type=Rank.parse,
        default=DEFAULT_RANK_RANGE.maximum,
        metavar="TIER-DIVISION",
        help=f"highest average rank (default: {DEFAULT_RANK_RANGE.maximum.slug})",
    )


def _epoch_boundary(value: str) -> EpochBoundary:
    identity, separator, raw_timestamp = value.rpartition("@")
    if not separator or not identity.strip():
        raise argparse.ArgumentTypeError("epoch must use IDENTITY@UNIX_TIMESTAMP")
    try:
        timestamp = int(raw_timestamp)
        return EpochBoundary(identity.strip(), timestamp)
    except (ValueError, TypeError) as error:
        raise argparse.ArgumentTypeError(
            "epoch must use IDENTITY@UNIX_TIMESTAMP"
        ) from error


def _snapshot_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--build-evidence",
        type=Path,
        help=(
            "validated player-match build evidence "
            "(default: build-evidence.json in the artifact directory)"
        ),
    )
    parser.add_argument(
        "--match-mode",
        type=MatchMode.parse,
        choices=tuple(MatchMode),
        default=MatchMode.RANKED,
        help="matchmaking population (default: ranked)",
    )
    parser.add_argument(
        "--client-version",
        type=positive_int,
        help="explicit available asset version (default: latest resolved once)",
    )
    parser.add_argument(
        "--as-of-timestamp",
        type=positive_int,
        help="immutable analytics upper cutoff (default: captured at startup)",
    )
    for name in ("mechanics", "matchmaking", "map-objectives", "telemetry"):
        parser.add_argument(
            f"--{name}-epoch",
            type=_epoch_boundary,
            metavar="IDENTITY@UNIX_TIMESTAMP",
            help="override one independent evidence-regime boundary",
        )


def _build_arguments(build: argparse.ArgumentParser) -> None:
    build_selection = build.add_mutually_exclusive_group()
    build_selection.add_argument("--hero", help="create builds for one active hero")
    build_selection.add_argument(
        "--all",
        action="store_true",
        help="create builds for all eligible heroes (default)",
    )
    _rank_arguments(build)
    _snapshot_arguments(build)
    build.add_argument(
        "--artifacts", type=Path, help="evidence and build artifact directory"
    )
    build.add_argument("--format", choices=("markdown", "json"), default="markdown")
    build.add_argument(
        "--details", action="store_true", help="show full optional routes and evidence"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="deadlock-build-sync",
        description="Generate private analytics-driven Deadlock hero builds.",
    )
    _trace_argument(parser, default=os.environ.get(TRACE_ENVIRONMENT_VARIABLE) or None)
    parser.add_argument("--api-base-url", default=DEFAULT_API_BASE_URL)
    subparsers = parser.add_subparsers(dest="command", required=True)

    sync = subparsers.add_parser(
        "sync",
        help="generate deterministic builds and install every reliable hero",
    )
    _common_location_arguments(sync)
    sync_selection = sync.add_mutually_exclusive_group()
    sync_selection.add_argument(
        "--hero",
        help="sync one active hero instead of every reliable hero",
    )
    sync_selection.add_argument(
        "--all",
        action="store_true",
        help="sync every active hero with complete reliable analytics (default)",
    )
    _rank_arguments(sync)
    _snapshot_arguments(sync)
    sync.add_argument(
        "--artifacts",
        type=Path,
        help="directory for reusable evidence and build artifacts",
    )

    build = subparsers.add_parser(
        "build", help="create complete Markdown and JSON builds without Steam"
    )
    _build_arguments(build)

    status = subparsers.add_parser(
        "status",
        help="check evidence, artifacts, and installed managed builds without changes",
    )
    _common_location_arguments(status)
    status.add_argument(
        "--artifacts",
        type=Path,
        help="artifact directory (default: user state directory)",
    )
    status.add_argument(
        "--json", action="store_true", help="emit machine-readable JSON"
    )
    refresh = subparsers.add_parser(
        "refresh-evidence",
        help="rebuild current deidentified evidence without reading or writing Steam",
    )
    refresh.add_argument("--artifacts", type=Path, help="artifact output directory")
    refresh.add_argument("--run-id", help="stable offline run identifier")
    _rank_arguments(refresh)
    refresh.add_argument("--min-badge", type=positive_int)
    refresh.add_argument("--max-badge", type=positive_int)
    refresh.add_argument("--since", help="cohort lower timestamp in ISO-8601 form")
    refresh.add_argument("--as-of", help="frozen upper timestamp in ISO-8601 form")
    recommendation = subparsers.add_parser(
        "recommend",
        help="return a read-only next action for a deidentified state file",
    )
    recommendation.add_argument("--state", type=Path, required=True)
    recommendation.add_argument("--build-evidence", type=Path)
    recommendation.add_argument(
        "--policies",
        type=Path,
        help="typed policy sidecar (default: policies.json beside build evidence)",
    )
    recommendation.add_argument("--artifacts", type=Path)
    recommendation.add_argument(
        "--format", choices=("json", "markdown"), default="json"
    )
    quality = subparsers.add_parser(
        "quality-report",
        help="audit frozen build quality and optional later replay without Steam or network",
    )
    quality.add_argument("--artifacts", type=Path)
    quality.add_argument(
        "--replay", type=Path, help="deidentified later decision replay JSON"
    )
    quality.add_argument(
        "--assets", type=Path, help="item assets pinned to build evidence"
    )
    preview = subparsers.add_parser(
        "preview", help="generate and print guides without changing Steam data"
    )
    _common_location_arguments(preview)
    _hero_arguments(preview)
    _rank_arguments(preview)
    _snapshot_arguments(preview)
    _narrative_argument(preview)
    preview.add_argument("--format", choices=("json", "markdown"), default="json")
    preview.add_argument("--details", action="store_true")

    install = subparsers.add_parser(
        "install", help="install private guides into My Builds"
    )
    _common_location_arguments(install)
    _hero_arguments(install)
    _rank_arguments(install)
    _snapshot_arguments(install)
    _narrative_argument(install)

    install_artifacts = subparsers.add_parser(
        "install-artifacts",
        help="install one reviewed artifact bundle without refetching analytics",
    )
    _common_location_arguments(install_artifacts)
    install_artifacts.add_argument(
        "--artifacts",
        type=Path,
        help=(
            "directory containing build-evidence.json, strategy-context.json, "
            "policies.json, and narratives.json"
        ),
    )
    install_artifacts.add_argument(
        "--persona",
        help="name prefix shown on installed builds (default: local Steam persona)",
    )

    export_context = subparsers.add_parser(
        "export-context",
        help="export structured item and ability context for reviewed artifacts",
    )
    _common_location_arguments(export_context)
    _hero_arguments(export_context)
    _rank_arguments(export_context)
    _snapshot_arguments(export_context)
    export_context.add_argument("--output", type=Path, required=True)
    export_context.add_argument(
        "--policy-output",
        type=Path,
        help="rich policy sidecar (default: policies.json beside --output)",
    )

    restore = subparsers.add_parser("restore", help="restore a backed-up build cache")
    _common_location_arguments(restore)
    restore.add_argument("--latest", action="store_true", required=True)

    trace_summary = subparsers.add_parser(
        "trace-summary",
        help="render a trace call tree and per-function inclusive time",
    )
    trace_summary.add_argument("path", type=Path, help="trace directory or JSONL file")
    trace_summary.add_argument(
        "--max-nodes",
        type=positive_int,
        default=200,
        help="maximum call-tree nodes to print (default: 200)",
    )

    for command_parser in (
        sync,
        build,
        status,
        refresh,
        recommendation,
        quality,
        preview,
        install,
        install_artifacts,
        export_context,
        restore,
        trace_summary,
    ):
        _trace_argument(command_parser, default=argparse.SUPPRESS)
    return parser
