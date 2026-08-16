from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from scripts.generate_narratives import (
    DEFAULT_GENERATION_ATTEMPTS,
    positive_int,
)
from scripts.generate_narratives import main as generate_narratives_main

from .api import DEFAULT_API_BASE_URL, ApiError, DeadlockApi
from .artifact_bundle import load_artifact_guide_bundle
from .artifacts import atomic_write_json, build_policy_artifact
from .build_evidence import BuildEvidenceCatalog, load_build_evidence
from .cache import (
    CacheError,
    CacheLocation,
    deadlock_is_running,
    discover_cache,
    install_guides,
    restore_latest,
)
from .freshness import (
    FreshnessError,
    build_freshness_report,
    require_current_build_evidence,
)
from .narratives import (
    DEFAULT_KIT_MODEL,
    DEFAULT_SYNTHESIS_MODEL,
    NarrativeCatalog,
    NarrativeError,
    apply_narrative,
    load_narrative_catalog,
)
from .presentation import build_presentation
from .protobuf import describe_guide, encode_hero_build
from .ranks import DEFAULT_RANK_RANGE, Rank, RankRange
from .recommendation import DecisionState, RecommendationError, recommend
from .service import GuideError, generate_guides
from .snapshot import EpochBoundary, EpochSet, MatchMode
from .steam_identity import local_steam_persona
from .strategy_context import build_strategy_context_document
from .tracing import (
    TRACE_ENVIRONMENT_VARIABLE,
    TraceError,
    TraceMode,
    TraceSession,
    record_stage_facts,
    render_trace_summary,
)

if TYPE_CHECKING:
    from .purchase_guide import PurchaseGuide
    from .service import GeneratedGuides

DEFAULT_NARRATIVE_PATH = Path("generated/narratives.json")


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="deadlock-build-sync",
        description="Generate private analytics-driven Deadlock hero builds.",
    )
    environment_trace = os.environ.get(TRACE_ENVIRONMENT_VARIABLE) or None
    _trace_argument(parser, default=environment_trace)
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
    _snapshot_arguments(sync)
    sync.add_argument(
        "--artifacts",
        type=Path,
        help="directory for reusable context, kit, and narrative artifacts",
    )

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
    refresh.add_argument("--min-badge", type=positive_int, default=71)
    refresh.add_argument("--max-badge", type=positive_int, default=115)
    refresh.add_argument("--since", help="cohort lower timestamp in ISO-8601 form")
    refresh.add_argument("--as-of", help="frozen upper timestamp in ISO-8601 form")
    refresh.add_argument(
        "--xgb-device",
        choices=("auto", "cpu", "cuda"),
        default="auto",
        help="XGBoost device; auto prefers CUDA and falls back to CPU",
    )
    recommendation = subparsers.add_parser(
        "recommend",
        help="return a read-only next action for a deidentified state file",
    )
    recommendation.add_argument("--state", type=Path, required=True)
    recommendation.add_argument("--build-evidence", type=Path)
    recommendation.add_argument("--artifacts", type=Path)
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
    _snapshot_arguments(preview)
    _narrative_argument(preview)

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
        help="export structured item and ability context for the Codex sidecar",
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
        status,
        refresh,
        recommendation,
        preview,
        install,
        install_artifacts,
        export_context,
        restore,
        trace_summary,
    ):
        _trace_argument(command_parser, default=argparse.SUPPRESS)
    return parser


def _location(args: argparse.Namespace) -> CacheLocation:
    return discover_cache(account_id=args.account_id, cache_path=args.cache_path)


def _catalog(args: argparse.Namespace) -> NarrativeCatalog | None:
    return load_narrative_catalog(args.narratives) if args.narratives else None


def _rank_range(args: argparse.Namespace) -> RankRange:
    return RankRange(args.min_rank, args.max_rank)


def _epochs(args: argparse.Namespace) -> EpochSet | None:
    values = (
        args.mechanics_epoch,
        args.matchmaking_epoch,
        args.map_objectives_epoch,
        args.telemetry_epoch,
    )
    if not any(values):
        return None
    if not all(isinstance(value, EpochBoundary) for value in values):
        raise ValueError("provide all four epoch overrides together")
    mechanics, matchmaking, map_objectives, telemetry = values
    return EpochSet(mechanics, matchmaking, map_objectives, telemetry)


def _api(args: argparse.Namespace, evidence: BuildEvidenceCatalog) -> DeadlockApi:
    return DeadlockApi(
        args.api_base_url,
        rank_range=_rank_range(args),
        match_mode=args.match_mode,
        client_version=args.client_version or evidence.client_version,
        as_of_timestamp=args.as_of_timestamp or evidence.as_of_timestamp,
        epochs=_epochs(args) or evidence.epochs,
    )


def _report_skipped(generated: GeneratedGuides) -> None:
    if generated.skipped_heroes:
        print(
            "Skipped heroes with incomplete analytics: "
            + ", ".join(generated.skipped_heroes),
            file=sys.stderr,
        )
    for policy in generated.policies:
        for abstention in policy.abstentions:
            print(
                f"Abstained claim for hero {policy.hero_id} "
                f"({abstention.reason.value}): {abstention.detail}",
                file=sys.stderr,
            )


def _sync_artifact_directory(configured: Path | None) -> Path:
    if configured is not None:
        return configured.expanduser().resolve()
    state_home = os.environ.get("XDG_STATE_HOME")
    root = Path(state_home).expanduser() if state_home else Path.home() / ".local/state"
    return root / "deadlock-build-sync/artifacts"


def _build_evidence_path(args: argparse.Namespace) -> Path:
    if args.build_evidence is not None:
        return args.build_evidence.expanduser().resolve()
    configured = args.artifacts if args.command == "sync" else None
    return _sync_artifact_directory(configured) / "build-evidence.json"


def _build_evidence(args: argparse.Namespace) -> tuple[Path, BuildEvidenceCatalog]:
    path = _build_evidence_path(args)
    evidence = load_build_evidence(path)
    record_stage_facts(
        "evidence.admission",
        path=path,
        artifact_id=evidence.artifact_id,
        hero_count=len(evidence.heroes),
    )
    return path, evidence


def _write_strategy_context(path: Path, generated: GeneratedGuides) -> None:
    document = build_strategy_context_document(
        generated.patch,
        generated.contexts,
        manifest=generated.manifest,
        item_mechanics=generated.item_mechanics,
        requested_hero_ids=_requested_hero_ids(generated),
        exclusions=generated.exclusions,
    )
    atomic_write_json(path, document, compact=True)


def _requested_hero_ids(generated: GeneratedGuides) -> set[int]:
    if generated.subset_selected:
        return {guide.hero_id for guide in generated.guides}
    return set(generated.eligible_hero_ids)


def _write_policy_artifact(path: Path, generated: GeneratedGuides) -> None:
    document = build_policy_artifact(
        generated.policies,
        snapshot_manifest=generated.manifest.as_dict(),
        requested_hero_ids=_requested_hero_ids(generated),
        exclusions=generated.exclusions,
    )
    atomic_write_json(path, document)


def _record_generated_facts(generated: GeneratedGuides) -> None:
    record_stage_facts(
        "guide.generation",
        guide_count=len(generated.guides),
        policy_count=len(generated.policies),
        context_count=len(generated.contexts),
        skipped_count=len(generated.exclusions),
        snapshot_id=generated.manifest.snapshot_id,
    )


def _describe_preview_guide(
    guide: PurchaseGuide,
    generated: GeneratedGuides,
    *,
    account_id: int,
) -> dict[str, Any]:
    presentation = build_presentation(
        guide,
        patch_title=generated.patch.title,
        patch_published_at=generated.patch.published_at,
        rank_range=generated.rank_range,
    )
    # Preview traverses the pure serializer so it validates the same presentation
    # boundary as installation without reading or changing Steam data.
    encode_hero_build(
        presentation,
        build_id=1,
        account_id=account_id,
        timestamp=0,
    )
    return describe_guide(guide, presentation=presentation)


def _run_sync(args: argparse.Namespace) -> int:
    artifact_directory = _sync_artifact_directory(args.artifacts)
    evidence_path = _build_evidence_path(args)
    evidence = require_current_build_evidence(
        evidence_path,
        DeadlockApi(args.api_base_url),
    )
    record_stage_facts(
        "evidence.freshness",
        path=evidence_path,
        artifact_id=evidence.artifact_id,
        hero_count=len(getattr(evidence, "heroes", {})),
    )
    location = _location(args)
    if deadlock_is_running():
        raise CacheError("Deadlock is running; close it before syncing private builds")

    generated = generate_guides(
        _api(args, evidence),
        build_evidence=evidence,
        account_id=location.account_id,
        hero_query=args.hero,
        all_heroes=args.all or args.hero is None,
    )
    _record_generated_facts(generated)
    _report_skipped(generated)
    if not generated.guides:
        raise GuideError("no heroes had complete reliable analytics")
    if not generated.subset_selected and generated.exclusions:
        raise GuideError(
            "all-hero sync requires complete roster coverage; exclusions: "
            + ", ".join(generated.skipped_heroes)
        )

    context_path = artifact_directory / "strategy-context.json"
    policy_path = artifact_directory / "policies.json"
    kit_path = artifact_directory / "kit-profiles.json"
    narrative_path = artifact_directory / "narratives.json"
    _write_strategy_context(context_path, generated)
    _write_policy_artifact(policy_path, generated)
    record_stage_facts("artifact.write", path=context_path)
    record_stage_facts("artifact.write", path=policy_path)

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
    record_stage_facts("artifact.write", path=narrative_path)

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
        snapshot_manifest=generated.manifest.as_dict(),
        expected_hero_ids=set(generated.eligible_hero_ids),
        allow_subset=generated.subset_selected,
    )
    record_stage_facts(
        "steam.install",
        guide_count=len(result.build_ids),
        created=result.created,
        updated=result.updated,
        snapshot_id=result.snapshot_id,
    )
    print(
        f"Synced {len(result.build_ids)} private guide(s): "
        f"{result.created} created, {result.updated} updated."
    )
    print(f"Artifacts: {artifact_directory}")
    print(f"Build evidence: {evidence_path} ({evidence.artifact_id})")
    print(f"Cache: {result.cache_path}")
    print(f"Backup: {result.backup_directory}")
    print(f"Snapshot: {result.snapshot_id}")
    print(
        "Policies: "
        + ", ".join(
            f"{hero_id}={policy_id}"
            for hero_id, policy_id in sorted(result.policy_ids.items())
        )
    )
    print(
        f"Cohort: {generated.manifest.match_mode.value}, client "
        f"{generated.manifest.client_version}, as-of {generated.manifest.as_of_timestamp}"
    )
    print("Launch Deadlock, open a hero's build browser, and check My Builds.")
    return 0


def _run_status(args: argparse.Namespace) -> int:
    artifact_directory = _sync_artifact_directory(args.artifacts)
    cache_path: Path | None = None
    account_id: int | None = None
    try:
        location = _location(args)
    except CacheError:
        pass
    else:
        cache_path = location.cache_path
        account_id = location.account_id
    report = build_freshness_report(
        artifact_directory,
        DeadlockApi(args.api_base_url),
        cache_path=cache_path,
        account_id=account_id,
    )
    record_stage_facts(
        "status",
        row_count=len(report.stages),
        exit_code=report.exit_code,
    )
    if args.json:
        print(json.dumps(report.as_dict(), indent=2, ensure_ascii=False))
    else:
        label = {
            0: "CURRENT",
            1: "INVALID OR UNAVAILABLE — intervention required",
            2: "STALE — regeneration required",
        }[report.exit_code]
        print(label)
        print(
            f"Latest: client {report.latest_client_version} • "
            f"{report.latest_patch.title} ({report.latest_patch.published_at})"
        )
        for stage in report.stages:
            print(f"{stage.name}: {stage.state.value} — {stage.detail}")
    return report.exit_code


def _run_refresh_evidence(args: argparse.Namespace) -> int:
    try:
        from .offline.cli import main as offline_main
    except ImportError as error:
        raise GuideError(
            "refresh-evidence requires the analysis dependencies; "
            "install deadlock-build-sync[analysis]"
        ) from error
    output = _sync_artifact_directory(args.artifacts) / "build-evidence.json"
    forwarded = [
        "all",
        "--min-rank",
        str(args.min_badge),
        "--max-rank",
        str(args.max_badge),
        "--output",
        str(output),
        "--xgb-device",
        args.xgb_device,
    ]
    for flag, value in (
        ("--run-id", args.run_id),
        ("--since", args.since),
        ("--as-of", args.as_of),
    ):
        if value:
            forwarded.extend((flag, str(value)))
    result = offline_main(forwarded)
    if result == 0:
        loaded = load_build_evidence(output)
        record_stage_facts(
            "evidence.admission",
            path=output,
            artifact_id=loaded.artifact_id,
            hero_count=len(getattr(loaded, "heroes", {})),
        )
        print(f"Build evidence: {output} ({loaded.artifact_id})")
    return result


def _run_recommend(args: argparse.Namespace) -> int:
    evidence_path = (
        args.build_evidence.expanduser().resolve()
        if args.build_evidence is not None
        else _sync_artifact_directory(args.artifacts) / "build-evidence.json"
    )
    evidence = require_current_build_evidence(
        evidence_path,
        DeadlockApi(args.api_base_url),
    )
    record_stage_facts(
        "evidence.freshness",
        path=evidence_path,
        artifact_id=evidence.artifact_id,
        hero_count=len(getattr(evidence, "heroes", {})),
    )
    state = DecisionState.from_file(args.state.expanduser().resolve())
    pinned_api = DeadlockApi(
        args.api_base_url,
        client_version=evidence.client_version,
        as_of_timestamp=evidence.as_of_timestamp,
        epochs=evidence.epochs,
    )
    decision = recommend(evidence, state, pinned_api.items())
    print(json.dumps(decision.as_dict(), indent=2, ensure_ascii=False))
    return 0


def _run_preview(args: argparse.Namespace) -> int:
    location = _location(args)
    evidence_path, evidence = _build_evidence(args)
    generated = generate_guides(
        _api(args, evidence),
        build_evidence=evidence,
        account_id=location.account_id,
        hero_query=args.hero,
        all_heroes=args.all,
        narrative_catalog=_catalog(args),
    )
    _record_generated_facts(generated)
    _report_skipped(generated)
    payload = {
        "account_id": location.account_id,
        "persona": generated.persona,
        "snapshot_manifest": generated.manifest.as_dict(),
        "patch": generated.patch.as_dict(),
        "rank_range": generated.manifest.rank_range,
        "exclusions": [
            {"hero_id": hero_id, "reason": reason}
            for hero_id, reason in generated.exclusions
        ],
        "artifacts": {
            "build_evidence": str(evidence_path),
            "build_evidence_id": evidence.artifact_id,
            "context": None,
            "policy": "inline:policies",
            "narrative": str(args.narratives) if args.narratives else None,
        },
        "policies": [policy.as_dict() for policy in generated.policies],
        "guides": [
            _describe_preview_guide(
                guide,
                generated,
                account_id=location.account_id,
            )
            for guide in generated.guides
        ],
    }
    record_stage_facts(
        "preview.output",
        guide_count=len(generated.guides),
        policy_count=len(generated.policies),
    )
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


def _run_install(args: argparse.Namespace) -> int:
    location = _location(args)
    if deadlock_is_running():
        raise CacheError(
            "Deadlock is running; close it before installing private builds"
        )
    evidence_path, evidence = _build_evidence(args)
    generated = generate_guides(
        _api(args, evidence),
        build_evidence=evidence,
        account_id=location.account_id,
        hero_query=args.hero,
        all_heroes=args.all,
        narrative_catalog=_catalog(args),
    )
    _record_generated_facts(generated)
    _report_skipped(generated)
    result = install_guides(
        location,
        generated.guides,
        persona=generated.persona,
        timestamp=int(time.time()),
        patch_title=generated.patch.title,
        patch_published_at=generated.patch.published_at,
        rank_range=generated.rank_range,
        snapshot_manifest=generated.manifest.as_dict(),
        expected_hero_ids=set(generated.eligible_hero_ids),
        allow_subset=generated.subset_selected,
    )
    record_stage_facts(
        "steam.install",
        guide_count=len(result.build_ids),
        created=result.created,
        updated=result.updated,
        snapshot_id=result.snapshot_id,
    )
    print(
        f"Installed {len(result.build_ids)} private guide(s): "
        f"{result.created} created, {result.updated} updated."
    )
    print(f"Cache: {result.cache_path}")
    print(f"Backup: {result.backup_directory}")
    print(f"Narrative artifact: {args.narratives or 'disabled'}")
    print(f"Build evidence: {evidence_path} ({evidence.artifact_id})")
    print(f"Snapshot: {result.snapshot_id}")
    print(
        "Policies: "
        + ", ".join(
            f"{hero_id}={policy_id}"
            for hero_id, policy_id in sorted(result.policy_ids.items())
        )
    )
    print(
        f"Cohort: {generated.manifest.match_mode.value}, client "
        f"{generated.manifest.client_version}, as-of "
        f"{generated.manifest.as_of_timestamp}"
    )
    print("Launch Deadlock, open the hero's build browser, and check My Builds.")
    return 0


def _run_install_artifacts(args: argparse.Namespace) -> int:
    location = _location(args)
    if deadlock_is_running():
        raise CacheError(
            "Deadlock is running; close it before installing private builds"
        )
    artifact_directory = _sync_artifact_directory(args.artifacts)
    context_path = artifact_directory / "strategy-context.json"
    policy_path = artifact_directory / "policies.json"
    narrative_path = artifact_directory / "narratives.json"
    build_evidence_path = artifact_directory / "build-evidence.json"
    bundle = load_artifact_guide_bundle(
        context_path,
        policy_path,
        narrative_path,
        build_evidence_path,
    )
    record_stage_facts(
        "artifact.admission",
        path=artifact_directory,
        guide_count=len(bundle.guides),
        skipped_count=len(bundle.exclusions),
        snapshot_id=str(bundle.snapshot_manifest["snapshot_id"]),
    )
    for hero_id, reason in bundle.exclusions:
        print(f"Skipped hero {hero_id}: {reason}", file=sys.stderr)
    persona = args.persona or local_steam_persona(location.account_id)
    if persona is None:
        raise CacheError(
            "could not resolve the local Steam persona; pass --persona explicitly"
        )
    result = install_guides(
        location,
        bundle.guides,
        persona=persona,
        timestamp=int(time.time()),
        patch_title=bundle.patch.title,
        patch_published_at=bundle.patch.published_at,
        rank_range=bundle.rank_range,
        snapshot_manifest=bundle.snapshot_manifest,
        expected_hero_ids=set(bundle.expected_hero_ids),
        allow_subset=False,
    )
    record_stage_facts(
        "steam.install",
        guide_count=len(result.build_ids),
        created=result.created,
        updated=result.updated,
        snapshot_id=result.snapshot_id,
    )
    print(
        f"Installed {len(result.build_ids)} reviewed private guide(s): "
        f"{result.created} created, {result.updated} updated."
    )
    print(f"Artifacts: {artifact_directory}")
    print(f"Build evidence: {build_evidence_path}")
    print(f"Strategy context: {context_path}")
    print(f"Policies: {policy_path}")
    print(f"Narratives: {narrative_path}")
    print(f"Cache: {result.cache_path}")
    print(f"Backup: {result.backup_directory}")
    print(f"Snapshot: {result.snapshot_id}")
    print(
        "Policies: "
        + ", ".join(
            f"{hero_id}={policy_id}"
            for hero_id, policy_id in sorted(result.policy_ids.items())
        )
    )
    print(
        f"Cohort: {bundle.snapshot_manifest['match_mode']}, client "
        f"{bundle.snapshot_manifest['client_version']}, as-of "
        f"{bundle.snapshot_manifest['as_of_timestamp']}"
    )
    print("Launch Deadlock, open a hero's build browser, and check My Builds.")
    return 0


def _run_export_context(args: argparse.Namespace) -> int:
    location = _location(args)
    evidence_path, evidence = _build_evidence(args)
    generated = generate_guides(
        _api(args, evidence),
        build_evidence=evidence,
        account_id=location.account_id,
        hero_query=args.hero,
        all_heroes=args.all,
    )
    _record_generated_facts(generated)
    _report_skipped(generated)
    document = build_strategy_context_document(
        generated.patch,
        generated.contexts,
        manifest=generated.manifest,
        item_mechanics=generated.item_mechanics,
        requested_hero_ids=_requested_hero_ids(generated),
        exclusions=generated.exclusions,
    )
    atomic_write_json(args.output, document, compact=True)
    record_stage_facts("artifact.write", path=args.output)
    policy_output = args.policy_output or args.output.with_name("policies.json")
    _write_policy_artifact(policy_output, generated)
    record_stage_facts("artifact.write", path=policy_output)
    print(f"Exported {len(generated.contexts)} hero context(s): {args.output}")
    print(f"Policies: {policy_output}")
    print(f"Build evidence: {evidence_path} ({evidence.artifact_id})")
    print(f"Snapshot: {generated.manifest.snapshot_id}")
    return 0


def _run_restore(args: argparse.Namespace) -> int:
    location = _location(args)
    restored = restore_latest(location)
    print(f"Restored cache backup: {restored}")
    print(f"Cache: {location.cache_path}")
    return 0


def _run_trace_summary(args: argparse.Namespace) -> int:
    print(render_trace_summary(args.path.expanduser(), max_nodes=args.max_nodes))
    return 0


def _dispatch(args: argparse.Namespace) -> int:
    handlers = {
        "sync": _run_sync,
        "status": _run_status,
        "refresh-evidence": _run_refresh_evidence,
        "recommend": _run_recommend,
        "preview": _run_preview,
        "install": _run_install,
        "install-artifacts": _run_install_artifacts,
        "export-context": _run_export_context,
        "restore": _run_restore,
        "trace-summary": _run_trace_summary,
    }
    return handlers[args.command](args)


def _run_command(args: argparse.Namespace) -> int:
    try:
        return _dispatch(args)
    except (
        ApiError,
        CacheError,
        GuideError,
        FreshnessError,
        NarrativeError,
        RecommendationError,
        OSError,
        ValueError,
    ) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.trace is None:
        return _run_command(args)

    session = TraceSession(args.trace, args.command)
    try:
        with session:
            result = _run_command(args)
            session.finish(result)
    finally:
        if session.directory is not None:
            print(f"Trace: {session.directory}", file=sys.stderr)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
