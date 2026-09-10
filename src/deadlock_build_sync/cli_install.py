from __future__ import annotations

from typing import TYPE_CHECKING

from .cache import (
    CacheError,
    deadlock_is_running,
)
from .cli_support import (
    _discover_cache_location,
    _generate_requested_guides,
    _install_generated_guides,
    _load_build_evidence,
    _load_optional_narrative_catalog,
    _print_cohort,
    _print_install_result,
)

if TYPE_CHECKING:
    import argparse


def _run_install(args: argparse.Namespace) -> int:
    location = _discover_cache_location(args)
    if deadlock_is_running():
        raise CacheError(
            "Deadlock is running; close it before installing private builds"
        )
    evidence_path, evidence = _load_build_evidence(args)
    generated = _generate_requested_guides(
        args,
        evidence,
        location.account_id,
        narrative_catalog=_load_optional_narrative_catalog(args),
    )
    result = _install_generated_guides(location, generated.guides, generated)
    print(
        f"Installed {len(result.build_ids)} private guide(s): "
        f"{result.created} created, {result.updated} updated, "
        f"{result.removed} stale removed."
    )
    print(f"Narrative artifact: {args.narratives or 'disabled'}")
    print(f"Build evidence: {evidence_path} ({evidence.artifact_id})")
    _print_install_result(result)
    _print_cohort(
        generated.manifest.match_mode.value,
        generated.manifest.client_version,
        generated.manifest.as_of_timestamp,
    )
    print("Launch Deadlock, open the hero's build browser, and check My Builds.")
    return 0
