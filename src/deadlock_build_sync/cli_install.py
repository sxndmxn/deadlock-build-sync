from __future__ import annotations

import time
from typing import TYPE_CHECKING

from .cache import (
    CacheError,
    deadlock_is_running,
    install_guides,
)
from .cli_support import (
    _POLICIES_PREFIX,
    _STEAM_INSTALL_STAGE,
    _api,
    _build_evidence,
    _catalog,
    _location,
    _record_generated_facts,
    _report_skipped,
)
from .service import generate_guides
from .tracing import record_stage_facts

if TYPE_CHECKING:
    import argparse


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
        _STEAM_INSTALL_STAGE,
        guide_count=len(result.build_ids),
        created=result.created,
        updated=result.updated,
        removed=result.removed,
        snapshot_id=result.snapshot_id,
    )
    print(
        f"Installed {len(result.build_ids)} private guide(s): "
        f"{result.created} created, {result.updated} updated, "
        f"{result.removed} stale removed."
    )
    print(f"Cache: {result.cache_path}")
    print(f"Backup: {result.backup_directory}")
    print(f"Narrative artifact: {args.narratives or 'disabled'}")
    print(f"Build evidence: {evidence_path} ({evidence.artifact_id})")
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
        f"{generated.manifest.client_version}, as-of "
        f"{generated.manifest.as_of_timestamp}"
    )
    print("Launch Deadlock, open the hero's build browser, and check My Builds.")
    return 0
