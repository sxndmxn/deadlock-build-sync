from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from .api import DeadlockApi
from .artifacts import ArtifactError, atomic_write_json, build_policy_artifact
from .build_evidence import BuildEvidenceCatalog, load_build_evidence
from .cache import (
    CacheLocation,
    InstallResult,
    discover_cache,
    install_guides,
)
from .narratives import (
    NarrativeCatalog,
    load_narrative_catalog,
)
from .presentation import build_presentation
from .protobuf import describe_guide, encode_hero_build
from .ranks import RankRange
from .service import GeneratedGuides, generate_guides
from .snapshot import EpochBoundary, EpochSet
from .strategy_context import build_strategy_context_document
from .tracing import record_stage_facts

if TYPE_CHECKING:
    import argparse

    from .purchase_guide import PurchaseGuide

DEFAULT_NARRATIVE_PATH = Path("generated/narratives.json")
_BUILD_EVIDENCE_FILENAME = "build-evidence.json"
_POLICY_FILENAME = "policies.json"
_ARTIFACT_WRITE_STAGE = "artifact.write"
_STEAM_INSTALL_STAGE = "steam.install"
_POLICIES_PREFIX = "Policies: "


@dataclass(frozen=True)
class _InstallSpec:
    persona: str
    patch_title: str
    patch_published_at: str
    rank_range: RankRange
    snapshot_manifest: dict[str, object]
    expected_hero_ids: set[int]
    allow_subset: bool


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
    if args.rank_expansion == "off" and any(
        build.cohort is not None and build.cohort.minimum_badge < args.min_rank.badge_id
        for build in evidence.heroes.values()
    ):
        raise ArtifactError(
            "Evidence uses expanded ranks. Run deadlock-build-sync refresh-evidence --rank-expansion off, then build again."
        )
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
            "Skipped heroes with evidence exclusions: "
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
    configured = args.artifacts if args.command in {"sync", "build"} else None
    return _sync_artifact_directory(configured) / _BUILD_EVIDENCE_FILENAME


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


def _record_fresh_evidence(path: Path, evidence: BuildEvidenceCatalog) -> None:
    record_stage_facts(
        "evidence.freshness",
        path=path,
        artifact_id=evidence.artifact_id,
        hero_count=len(evidence.heroes),
    )


def _generate(
    args: argparse.Namespace,
    evidence: BuildEvidenceCatalog,
    account_id: int,
    *,
    all_heroes: bool | None = None,
    narrative_catalog: NarrativeCatalog | None = None,
) -> GeneratedGuides:
    generated = generate_guides(
        _api(args, evidence),
        build_evidence=evidence,
        account_id=account_id,
        hero_query=args.hero,
        all_heroes=args.all if all_heroes is None else all_heroes,
        narrative_catalog=narrative_catalog,
    )
    _record_generated_facts(generated)
    _report_skipped(generated)
    return generated


def _install_and_record(
    location: CacheLocation,
    guides: list[PurchaseGuide],
    spec: _InstallSpec,
) -> InstallResult:
    result = install_guides(
        location,
        guides,
        persona=spec.persona,
        timestamp=int(time.time()),
        patch_title=spec.patch_title,
        patch_published_at=spec.patch_published_at,
        rank_range=spec.rank_range,
        snapshot_manifest=spec.snapshot_manifest,
        expected_hero_ids=spec.expected_hero_ids,
        allow_subset=spec.allow_subset,
    )
    record_stage_facts(
        _STEAM_INSTALL_STAGE,
        guide_count=len(result.build_ids),
        created=result.created,
        updated=result.updated,
        removed=result.removed,
        snapshot_id=result.snapshot_id,
    )
    return result


def _install_generated_guides(
    location: CacheLocation,
    guides: list[PurchaseGuide],
    generated: GeneratedGuides,
) -> InstallResult:
    return _install_and_record(
        location,
        guides,
        _InstallSpec(
            persona=generated.persona,
            patch_title=generated.patch.title,
            patch_published_at=generated.patch.published_at,
            rank_range=generated.rank_range,
            snapshot_manifest=generated.manifest.as_dict(),
            expected_hero_ids=set(generated.eligible_hero_ids)
            - {hero for hero, _ in generated.exclusions},
            allow_subset=generated.subset_selected,
        ),
    )


def _print_install_result(result: InstallResult) -> None:
    print(f"Cache: {result.cache_path}")
    print(f"Backup: {result.backup_directory}")
    print(f"Snapshot: {result.snapshot_id}")
    policies = ", ".join(
        f"{hero_id}/{path_id}={policy_id}"
        for (hero_id, path_id), policy_id in sorted(result.policy_ids.items())
    )
    print(_POLICIES_PREFIX + policies)


def _print_cohort(
    match_mode: object,
    client_version: object,
    as_of_timestamp: object,
) -> None:
    print(f"Cohort: {match_mode}, client {client_version}, as-of {as_of_timestamp}")


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
) -> dict[str, object]:
    presentation = build_presentation(
        guide,
        persona=generated.persona,
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
    described = describe_guide(guide, presentation=presentation)
    described["purchase_guidance"] = (
        guide.purchase_guidance.as_dict() if guide.purchase_guidance else None
    )
    return described
