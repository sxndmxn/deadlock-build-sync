from __future__ import annotations

import json
import shutil
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from typing import TYPE_CHECKING

from scripts.generate_narratives import main as generate_narratives_main

from .api import ApiError, DeadlockApi
from .artifact_bundle import load_artifact_guide_bundle
from .artifacts import atomic_write_bytes, atomic_write_json
from .build_evidence import load_build_evidence
from .cache import (
    CacheError,
    deadlock_is_running,
)
from .cli_build import write_build_guides
from .cli_export import _run_export_context, _run_restore, _run_trace_summary
from .cli_install import _run_install
from .cli_parser import DEFAULT_NARRATIVE_PATH, build_parser, parse_positive_integer
from .cli_quality import run_quality_report
from .cli_recommend import _run_preview, _run_recommend
from .cli_status import _run_status
from .cli_support import (
    _ARTIFACT_WRITE_STAGE,
    _BUILD_EVIDENCE_FILENAME,
    _POLICY_FILENAME,
    _describe_preview_guide,
    _discover_cache_location,
    _generate_requested_guides,
    _install_and_record,
    _install_generated_guides,
    _InstallationParameters,
    _print_cohort,
    _print_install_result,
    _record_fresh_evidence,
    _resolve_artifact_directory,
    _resolve_build_evidence_path,
    _write_policy_artifact,
    _write_strategy_context,
)
from .freshness import (
    FreshnessError,
    require_current_build_evidence,
)
from .guide_generator import require_generator
from .guide_groups import group_guides
from .narratives import (
    NarrativeError,
    apply_narrative,
    load_narrative_catalog,
)
from .purchase_markdown import render_purchase_markdown
from .recommendation import RecommendationError
from .service import GuideError
from .steam_identity import local_steam_persona
from .tracing import (
    TraceSession,
    record_stage_facts,
)

if TYPE_CHECKING:
    import argparse

    from .build_evidence import BuildEvidenceCatalog
    from .purchase_guide import PurchaseGuide
    from .service import GeneratedGuides

__all__ = [
    "DEFAULT_NARRATIVE_PATH",
    "build_main",
    "build_parser",
    "main",
    "parse_positive_integer",
]


def _current_evidence(args: argparse.Namespace) -> tuple[Path, BuildEvidenceCatalog]:
    evidence_path = _resolve_build_evidence_path(args)
    evidence = require_current_build_evidence(
        evidence_path, DeadlockApi(args.api_base_url)
    )
    require_generator(getattr(args, "generator", "current"), evidence.generator)
    _record_fresh_evidence(evidence_path, evidence)
    return evidence_path, evidence


def _require_complete(generated: GeneratedGuides) -> None:
    if not generated.guides:
        raise GuideError("no heroes had complete reliable analytics")
    covered = {guide.hero_id for guide in generated.guides}
    if generated.exclusions:
        raise GuideError("Requested heroes have no supported builds")
    if not generated.subset_selected and covered != generated.eligible_hero_ids:
        raise GuideError("Build evidence does not cover every requested hero")


def _run_build(args: argparse.Namespace) -> int:
    directory = _resolve_artifact_directory(args.artifacts)
    _, evidence = _current_evidence(args)
    generated = _generate_requested_guides(
        args, evidence, 0, all_heroes=args.all or args.hero is None
    )
    _require_complete(generated)
    guides = _write_build_artifacts(generated, directory, evidence)
    if args.format == "markdown":
        print(
            "\n".join(
                render_purchase_markdown(guide, details=args.details)
                for guide in guides
            )
        )
    else:
        print(
            json.dumps(
                {
                    "snapshot_manifest": generated.manifest.as_dict(),
                    "guides": [
                        _describe_preview_guide(guide, generated, account_id=0)
                        for guide in guides
                    ],
                },
                indent=2,
                ensure_ascii=False,
            )
        )
    print(f"Build files: {directory / 'builds.json'}", file=sys.stderr)
    return 0


def _write_build_artifacts(
    generated: GeneratedGuides,
    artifact_directory: Path,
    evidence: BuildEvidenceCatalog,
) -> list[PurchaseGuide]:
    artifact_directory.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(
            prefix=f".{artifact_directory.name}.", dir=artifact_directory.parent
        )
    )
    staged, previous = temporary / "new", temporary / "previous"
    committed = False
    try:
        if artifact_directory.exists():
            shutil.copytree(artifact_directory, staged)
        else:
            staged.mkdir()
        atomic_write_bytes(staged / _BUILD_EVIDENCE_FILENAME, evidence.raw_bytes)
        guides = _render_build_artifacts(generated, staged)
        index = json.loads((staged / "builds.json").read_text(encoding="utf-8"))
        index["directory"] = str(
            artifact_directory / "builds" / generated.manifest.snapshot_id
        )
        atomic_write_json(staged / "builds.json", index)
        if artifact_directory.exists():
            artifact_directory.rename(previous)
        try:
            staged.rename(artifact_directory)
        except OSError:
            if previous.exists():
                previous.rename(artifact_directory)
            raise
        committed = True
        return guides
    finally:
        if committed or not previous.exists():
            shutil.rmtree(temporary)


def _render_build_artifacts(
    generated: GeneratedGuides, artifact_directory: Path
) -> list[PurchaseGuide]:
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
    with redirect_stdout(sys.stderr):
        if generate_narratives_main(generation_args) != 0:
            raise NarrativeError("deterministic description generation failed")
    record_stage_facts(_ARTIFACT_WRITE_STAGE, path=narrative_path)

    catalog = load_narrative_catalog(narrative_path)
    guides = [
        apply_narrative(guide, context, generated.patch, catalog)
        for guide, context in zip(generated.guides, generated.contexts, strict=True)
    ]
    guides = group_guides(guides, generated.guide_groups)
    write_build_guides(artifact_directory, guides, generated)
    return guides


def _run_sync(args: argparse.Namespace) -> int:
    artifact_directory = _resolve_artifact_directory(args.artifacts)
    evidence_path, evidence = _current_evidence(args)
    location = _discover_cache_location(args)
    if deadlock_is_running():
        raise CacheError("Deadlock is running; close it before syncing private builds")

    generated = _generate_requested_guides(
        args,
        evidence,
        location.account_id,
        all_heroes=args.all or args.hero is None,
    )
    _require_complete(generated)

    guides = _write_build_artifacts(generated, artifact_directory, evidence)
    result = _install_generated_guides(location, guides, generated)
    print(
        f"Synced {len(result.build_ids)} private guide(s): "
        f"{result.created} created, {result.updated} updated, "
        f"{result.removed} stale removed."
    )
    print(f"Artifacts: {artifact_directory}")
    print(f"Build evidence: {evidence_path} ({evidence.artifact_id})")
    _print_install_result(result)
    _print_cohort(
        generated.manifest.match_mode.value,
        generated.manifest.client_version,
        generated.manifest.as_of_timestamp,
    )
    print("Launch Deadlock, open a hero's build browser, and check My Builds.")
    return 0


def _run_refresh_evidence(args: argparse.Namespace) -> int:
    try:
        from .offline.refresh import main as offline_main
    except ImportError as error:
        raise GuideError(
            "refresh-evidence requires the analysis dependencies; "
            "install deadlock-build-sync[analysis]"
        ) from error
    output = _resolve_artifact_directory(args.artifacts) / _BUILD_EVIDENCE_FILENAME
    forwarded = [
        "--rank-expansion",
        args.rank_expansion,
        "--min-rank",
        str(args.min_badge or args.min_rank.badge_id),
        "--max-rank",
        str(args.max_badge or args.max_rank.badge_id),
        "--output",
        str(output),
        "--workers",
        str(args.workers),
    ]
    for flag, value in (
        ("--run-id", args.run_id),
        ("--since", args.since),
        ("--as-of", args.as_of),
    ):
        if value:
            forwarded.extend((flag, str(value)))
    if args.resume:
        forwarded.append("--resume")
    if getattr(args, "generator", "current") != "current":
        forwarded.extend(("--generator", args.generator))
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
    location = _discover_cache_location(args)
    if deadlock_is_running():
        raise CacheError(
            "Deadlock is running; close it before installing private builds"
        )
    artifact_directory = _resolve_artifact_directory(args.artifacts)
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
    result = _install_and_record(
        location,
        bundle.guides,
        _InstallationParameters(
            persona=persona,
            patch_title=bundle.patch.title,
            patch_published_at=bundle.patch.published_at,
            rank_range=bundle.rank_range,
            snapshot_manifest=bundle.snapshot_manifest,
            expected_hero_ids=set(bundle.expected_hero_ids),
            allow_subset=False,
        ),
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
    _print_install_result(result)
    _print_cohort(
        bundle.snapshot_manifest["match_mode"],
        bundle.snapshot_manifest["client_version"],
        bundle.snapshot_manifest["as_of_timestamp"],
    )
    print("Launch Deadlock, open a hero's build browser, and check My Builds.")
    return 0


def _dispatch(args: argparse.Namespace) -> int:
    handlers = {
        "build": _run_build,
        "sync": _run_sync,
        "status": _run_status,
        "refresh-evidence": _run_refresh_evidence,
        "recommend": _run_recommend,
        "quality-report": run_quality_report,
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


def build_main() -> int:
    """Support the short `uv run build` command.

    Returns:
        The build command exit status.

    """
    return main(["build", *sys.argv[1:]])


if __name__ == "__main__":
    raise SystemExit(main())
