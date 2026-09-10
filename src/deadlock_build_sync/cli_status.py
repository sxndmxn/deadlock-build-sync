from __future__ import annotations

import json
from typing import TYPE_CHECKING

from .api import DeadlockApi
from .cache import (
    CacheError,
)
from .cli_support import _discover_cache_location, _resolve_artifact_directory
from .freshness import (
    build_freshness_report,
)
from .tracing import record_stage_facts

if TYPE_CHECKING:
    import argparse
    from pathlib import Path


def _run_status(args: argparse.Namespace) -> int:
    artifact_directory = _resolve_artifact_directory(args.artifacts)
    cache_path: Path | None = None
    account_id: int | None = None
    try:
        location = _discover_cache_location(args)
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
