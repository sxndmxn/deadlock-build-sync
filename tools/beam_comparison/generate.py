"""Generate complete review artifacts without a Steam write or freshness bypass in sync."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from deadlock_build_sync import cli
from deadlock_build_sync.api import DeadlockApi
from deadlock_build_sync.artifacts import atomic_write_json
from deadlock_build_sync.build_evidence import load_build_evidence
from deadlock_build_sync.ranks import Rank, RankDivision, RankRange, RankTier
from deadlock_build_sync.service import generate_guides
from deadlock_build_sync.snapshot import MatchMode
from deadlock_build_sync.value_validation import integer
from tools.beam_comparison.snapshot_transport import SnapshotTransport


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument(
        "--mode", choices=("current", "beam-order", "beam"), required=True
    )
    args = parser.parse_args()
    directory = args.root / args.mode
    catalog = load_build_evidence(directory / "build-evidence.json")
    source = args.root / "source/results/master-0ecad50/raw"
    transport = SnapshotTransport(source, args.root / "api")
    started = time.monotonic()
    with DeadlockApi(
        client_version=catalog.client_version,
        as_of_timestamp=catalog.as_of_timestamp,
        epochs=catalog.epochs,
        rank_range=RankRange(
            *(
                Rank(
                    RankTier(integer(catalog.cohort[key]) // 10),
                    RankDivision(integer(catalog.cohort[key]) % 10),
                )
                for key in ("minimum_badge", "maximum_badge")
            )
        ),
        match_mode=MatchMode.RANKED,
        transport=transport,
    ) as api:
        # The transport controls requests that need a network response.
        api._http.set_request_interval(0)  # ruff: ignore[private-member-access]
        generated = generate_guides(
            api, build_evidence=catalog, account_id=0, hero_query=None, all_heroes=True
        )
    # Reuse the exact CLI artifact pipeline for this comparison.
    guides = cli._write_build_artifacts(generated, directory, catalog)  # ruff: ignore[private-member-access]
    atomic_write_json(
        directory / "generation.json",
        {
            "elapsed_seconds": time.monotonic() - started,
            "groups": len(guides),
            "variants": len(generated.guides),
            "snapshot_id": generated.manifest.snapshot_id,
            "source_artifact": catalog.artifact_id,
            "exploratory": True,
            "live_steam_sync": False,
        },
    )
    sys.stdout.write(f"Complete {args.mode} guides: {len(guides)} groups\n")


if __name__ == "__main__":
    main()
