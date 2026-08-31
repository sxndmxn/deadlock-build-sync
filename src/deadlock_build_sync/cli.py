from __future__ import annotations

import sys
import time
from typing import TYPE_CHECKING

from scripts.generate_narratives import main as generate_narratives_main

from .api import ApiError, DeadlockApi
from .artifact_bundle import load_artifact_guide_bundle
from .build_evidence import load_build_evidence
from .cache import (
    CacheError,
    deadlock_is_running,
    install_guides,
)
from .cli_export import _run_export_context, _run_restore, _run_trace_summary
from .cli_install import _run_install
from .cli_parser import DEFAULT_NARRATIVE_PATH, build_parser, positive_int
from .cli_recommend import _run_preview, _run_recommend
from .cli_status import _run_status
from .cli_support import (
    _ARTIFACT_WRITE_STAGE,
    _BUILD_EVIDENCE_FILENAME,
    _POLICIES_PREFIX,
    _POLICY_FILENAME,
    _STEAM_INSTALL_STAGE,
    _api,
    _build_evidence_path,
    _location,
    _record_generated_facts,
    _report_skipped,
    _sync_artifact_directory,
    _write_policy_artifact,
    _write_strategy_context,
)
from .freshness import (
    FreshnessError,
    require_current_build_evidence,
)
from .narratives import (
    NarrativeError,
    apply_narrative,
    load_narrative_catalog,
)
from .recommendation import RecommendationError
from .service import GuideError, generate_guides
from .steam_identity import local_steam_persona
from .tracing import (
    TraceSession,
    record_stage_facts,
)

if TYPE_CHECKING:
    import argparse

__all__ = ["DEFAULT_NARRATIVE_PATH", "build_parser", "main", "positive_int"]


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
    policy_path = artifact_directory / _POLICY_FILENAME
    narrative_path = artifact_directory / "narratives.json"
    _write_strategy_context(context_path, generated)
    _write_policy_artifact(policy_path, generated)
    record_stage_facts(_ARTIFACT_WRITE_STAGE, path=context_path)
    record_stage_facts(_ARTIFACT_WRITE_STAGE, path=policy_path)

    generation_args = [
        "--input",
        str(context_path),
        "--output",
        str(narrative_path),
    ]
    if generate_narratives_main(generation_args) != 0:
        raise NarrativeError("deterministic description generation failed")
    record_stage_facts(_ARTIFACT_WRITE_STAGE, path=narrative_path)

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
        _STEAM_INSTALL_STAGE,
        guide_count=len(result.build_ids),
        created=result.created,
        updated=result.updated,
        removed=result.removed,
        snapshot_id=result.snapshot_id,
    )
    print(
        f"Synced {len(result.build_ids)} private guide(s): "
        f"{result.created} created, {result.updated} updated, "
        f"{result.removed} stale removed."
    )
    print(f"Artifacts: {artifact_directory}")
    print(f"Build evidence: {evidence_path} ({evidence.artifact_id})")
    print(f"Cache: {result.cache_path}")
    print(f"Backup: {result.backup_directory}")
    print(f"Snapshot: {result.snapshot_id}")
    print(
        _POLICIES_PREFIX
        + ", ".join(
            f"{hero_id}/{path_id}={policy_id}"
            for (hero_id, path_id), policy_id in sorted(result.policy_ids.items())
        )
    )
    print(
        f"Cohort: {generated.manifest.match_mode.value}, client "
        f"{generated.manifest.client_version}, as-of {generated.manifest.as_of_timestamp}"
    )
    print("Launch Deadlock, open a hero's build browser, and check My Builds.")
    return 0


def _run_refresh_evidence(args: argparse.Namespace) -> int:
    try:
        from .offline.cli import main as offline_main
    except ImportError as error:
        raise GuideError(
            "refresh-evidence requires the analysis dependencies; "
            "install deadlock-build-sync[analysis]"
        ) from error
    output = _sync_artifact_directory(args.artifacts) / _BUILD_EVIDENCE_FILENAME
    forwarded = [
        "all",
        "--min-rank",
        str(args.min_badge),
        "--max-rank",
        str(args.max_badge),
        "--output",
        str(output),
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


def _run_install_artifacts(args: argparse.Namespace) -> int:
    location = _location(args)
    if deadlock_is_running():
        raise CacheError(
            "Deadlock is running; close it before installing private builds"
        )
    artifact_directory = _sync_artifact_directory(args.artifacts)
    context_path = artifact_directory / "strategy-context.json"
    policy_path = artifact_directory / _POLICY_FILENAME
    narrative_path = artifact_directory / "narratives.json"
    build_evidence_path = artifact_directory / _BUILD_EVIDENCE_FILENAME
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
        _STEAM_INSTALL_STAGE,
        guide_count=len(result.build_ids),
        created=result.created,
        updated=result.updated,
        removed=result.removed,
        snapshot_id=result.snapshot_id,
    )
    print(
        f"Installed {len(result.build_ids)} reviewed private guide(s): "
        f"{result.created} created, {result.updated} updated, "
        f"{result.removed} stale removed."
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
        _POLICIES_PREFIX
        + ", ".join(
            f"{hero_id}/{path_id}={policy_id}"
            for (hero_id, path_id), policy_id in sorted(result.policy_ids.items())
        )
    )
    print(
        f"Cohort: {bundle.snapshot_manifest['match_mode']}, client "
        f"{bundle.snapshot_manifest['client_version']}, as-of "
        f"{bundle.snapshot_manifest['as_of_timestamp']}"
    )
    print("Launch Deadlock, open a hero's build browser, and check My Builds.")
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
