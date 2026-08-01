from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

from scripts.generate_narratives import (
    DEFAULT_GENERATION_ATTEMPTS,
    positive_int,
)
from scripts.generate_narratives import main as generate_narratives_main

from .api import DEFAULT_API_BASE_URL, ApiError, DeadlockApi
from .cache import (
    CacheError,
    CacheLocation,
    deadlock_is_running,
    discover_cache,
    install_guides,
    restore_latest,
)
from .narratives import (
    DEFAULT_KIT_MODEL,
    DEFAULT_SYNTHESIS_MODEL,
    NarrativeCatalog,
    NarrativeError,
    apply_narrative,
    load_narrative_catalog,
)
from .protobuf import describe_guide
from .ranks import DEFAULT_RANK_RANGE, Rank, RankRange
from .service import GuideError, generate_guides
from .strategy_context import build_strategy_context_document

if TYPE_CHECKING:
    from .service import GeneratedGuides

DEFAULT_NARRATIVE_PATH = Path("generated/narratives.json")


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
            "reviewed Codex narrative artifact generated from export-context "
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="deadlock-build-sync",
        description="Generate private analytics-driven Deadlock hero builds.",
    )
    parser.add_argument("--api-base-url", default=DEFAULT_API_BASE_URL)
    subparsers = parser.add_subparsers(dest="command", required=True)

    sync = subparsers.add_parser(
        "sync",
        help="generate narratives and install every reliable hero into Steam",
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
    sync.add_argument(
        "--artifacts",
        type=Path,
        help="directory for reusable context, kit, and narrative artifacts",
    )
    sync.add_argument(
        "--kit-model",
        default=DEFAULT_KIT_MODEL,
        help=f"ability-only analysis model (default: {DEFAULT_KIT_MODEL})",
    )
    sync.add_argument(
        "--model",
        default=DEFAULT_SYNTHESIS_MODEL,
        help=f"final narrative model (default: {DEFAULT_SYNTHESIS_MODEL})",
    )
    sync.add_argument(
        "--force-narratives",
        action="store_true",
        help="regenerate kit profiles and narratives even when reusable",
    )
    sync.add_argument(
        "--max-attempts",
        type=positive_int,
        default=DEFAULT_GENERATION_ATTEMPTS,
        metavar="N",
        help=(
            "generation/validation attempts per model stage "
            f"(default: {DEFAULT_GENERATION_ATTEMPTS})"
        ),
    )

    preview = subparsers.add_parser(
        "preview", help="generate and print guides without changing Steam data"
    )
    _common_location_arguments(preview)
    _hero_arguments(preview)
    _rank_arguments(preview)
    _narrative_argument(preview)

    install = subparsers.add_parser(
        "install", help="install private guides into My Builds"
    )
    _common_location_arguments(install)
    _hero_arguments(install)
    _rank_arguments(install)
    _narrative_argument(install)

    export_context = subparsers.add_parser(
        "export-context",
        help="export structured item and ability context for the Codex sidecar",
    )
    _common_location_arguments(export_context)
    _hero_arguments(export_context)
    _rank_arguments(export_context)
    export_context.add_argument("--output", type=Path, required=True)

    restore = subparsers.add_parser("restore", help="restore a backed-up build cache")
    _common_location_arguments(restore)
    restore.add_argument("--latest", action="store_true", required=True)
    return parser


def _location(args: argparse.Namespace) -> CacheLocation:
    return discover_cache(account_id=args.account_id, cache_path=args.cache_path)


def _catalog(args: argparse.Namespace) -> NarrativeCatalog | None:
    return load_narrative_catalog(args.narratives) if args.narratives else None


def _rank_range(args: argparse.Namespace) -> RankRange:
    return RankRange(args.min_rank, args.max_rank)


def _report_skipped(generated: GeneratedGuides) -> None:
    if generated.skipped_heroes:
        print(
            "Skipped heroes with incomplete analytics: "
            + ", ".join(generated.skipped_heroes),
            file=sys.stderr,
        )


def _sync_artifact_directory(configured: Path | None) -> Path:
    if configured is not None:
        return configured.expanduser().resolve()
    state_home = os.environ.get("XDG_STATE_HOME")
    root = Path(state_home).expanduser() if state_home else Path.home() / ".local/state"
    return root / "deadlock-build-sync/artifacts"


def _write_strategy_context(path: Path, generated: GeneratedGuides) -> None:
    document = build_strategy_context_document(
        generated.patch,
        generated.contexts,
        generated.rank_range,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _run_sync(args: argparse.Namespace) -> int:
    location = _location(args)
    if deadlock_is_running():
        raise CacheError("Deadlock is running; close it before syncing private builds")

    generated = generate_guides(
        DeadlockApi(args.api_base_url, rank_range=_rank_range(args)),
        account_id=location.account_id,
        hero_query=args.hero,
        all_heroes=args.all or args.hero is None,
    )
    _report_skipped(generated)
    if not generated.guides:
        raise GuideError("no heroes had complete reliable analytics")

    artifact_directory = _sync_artifact_directory(args.artifacts)
    context_path = artifact_directory / "strategy-context.json"
    kit_path = artifact_directory / "kit-profiles.json"
    narrative_path = artifact_directory / "narratives.json"
    _write_strategy_context(context_path, generated)

    generation_args = [
        "--input",
        str(context_path),
        "--output",
        str(narrative_path),
        "--kit-output",
        str(kit_path),
        "--kit-model",
        args.kit_model,
        "--model",
        args.model,
        "--max-attempts",
        str(args.max_attempts),
    ]
    if args.force_narratives:
        generation_args.append("--force")
    if generate_narratives_main(generation_args) != 0:
        raise NarrativeError("Codex narrative generation failed")

    catalog = load_narrative_catalog(narrative_path)
    guides = [
        apply_narrative(guide, context, generated.patch, catalog)
        for guide, context in zip(generated.guides, generated.contexts, strict=True)
    ]
    result = install_guides(
        location,
        guides,
        persona=generated.persona,
        timestamp=int(time.time()),
        patch_title=generated.patch.title,
        patch_published_at=generated.patch.published_at,
        rank_range=generated.rank_range,
    )
    print(
        f"Synced {len(result.build_ids)} private guide(s): "
        f"{result.created} created, {result.updated} updated."
    )
    print(f"Artifacts: {artifact_directory}")
    print(f"Cache: {result.cache_path}")
    print(f"Backup: {result.backup_directory}")
    print("Launch Deadlock, open a hero's build browser, and check My Builds.")
    return 0


def _run_preview(args: argparse.Namespace) -> int:
    location = _location(args)
    generated = generate_guides(
        DeadlockApi(args.api_base_url, rank_range=_rank_range(args)),
        account_id=location.account_id,
        hero_query=args.hero,
        all_heroes=args.all,
        narrative_catalog=_catalog(args),
    )
    _report_skipped(generated)
    payload = {
        "account_id": location.account_id,
        "persona": generated.persona,
        "patch": {
            "title": generated.patch.title,
            "published_at": generated.patch.published_at,
            "start_timestamp": generated.patch.start_timestamp,
        },
        "rank_range": generated.rank_range.as_dict(),
        "guides": [describe_guide(guide) for guide in generated.guides],
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


def _run_install(args: argparse.Namespace) -> int:
    location = _location(args)
    if deadlock_is_running():
        raise CacheError(
            "Deadlock is running; close it before installing private builds"
        )
    generated = generate_guides(
        DeadlockApi(args.api_base_url, rank_range=_rank_range(args)),
        account_id=location.account_id,
        hero_query=args.hero,
        all_heroes=args.all,
        narrative_catalog=_catalog(args),
    )
    _report_skipped(generated)
    result = install_guides(
        location,
        generated.guides,
        persona=generated.persona,
        timestamp=int(time.time()),
        patch_title=generated.patch.title,
        patch_published_at=generated.patch.published_at,
        rank_range=generated.rank_range,
    )
    print(
        f"Installed {len(result.build_ids)} private guide(s): "
        f"{result.created} created, {result.updated} updated."
    )
    print(f"Cache: {result.cache_path}")
    print(f"Backup: {result.backup_directory}")
    print("Launch Deadlock, open the hero's build browser, and check My Builds.")
    return 0


def _run_export_context(args: argparse.Namespace) -> int:
    location = _location(args)
    generated = generate_guides(
        DeadlockApi(args.api_base_url, rank_range=_rank_range(args)),
        account_id=location.account_id,
        hero_query=args.hero,
        all_heroes=args.all,
    )
    _report_skipped(generated)
    document = build_strategy_context_document(
        generated.patch,
        generated.contexts,
        generated.rank_range,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(document, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Exported {len(generated.contexts)} hero context(s): {args.output}")
    return 0


def _run_restore(args: argparse.Namespace) -> int:
    location = _location(args)
    restored = restore_latest(location)
    print(f"Restored cache backup: {restored}")
    print(f"Cache: {location.cache_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handlers = {
        "sync": _run_sync,
        "preview": _run_preview,
        "install": _run_install,
        "export-context": _run_export_context,
        "restore": _run_restore,
    }
    try:
        return handlers[args.command](args)
    except (
        ApiError,
        CacheError,
        GuideError,
        NarrativeError,
        OSError,
        ValueError,
    ) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
