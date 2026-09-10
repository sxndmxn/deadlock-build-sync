"""Recover a comparison export from a complete frozen candidate family."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from deadlock_build_sync.guide_generator import generator_record
from deadlock_build_sync.offline.beam_export import (
    BeamValidationJob,
    validate_beam_hero,
)
from deadlock_build_sync.offline.beam_nomination import (
    BeamDiscoveryJob,
    BeamHeroProposals,
    BeamNomination,
)
from deadlock_build_sync.offline.discovery_snapshot import (
    require_discovery_source_identity,
)
from deadlock_build_sync.offline.discovery_workers import map_discovery_jobs
from deadlock_build_sync.snapshot import sha256_json
from deadlock_build_sync.value_validation import (
    integer,
    require_object_dict,
    require_object_rows,
)

if TYPE_CHECKING:
    from pathlib import Path

    from deadlock_build_sync.offline.discovery_types import NominatedCoreBuild
    from deadlock_build_sync.offline.production_sources import _HeroExportContext


@dataclass(frozen=True)
class RevalidationOptions:
    workers: int
    order_only: bool


def revalidate_roster(
    path: Path,
    heroes: list[dict[str, object]],
    baseline: list[dict[str, object]],
    context: _HeroExportContext,
    *,
    options: RevalidationOptions,
) -> list[dict[str, object]]:
    frozen = require_object_dict(json.loads(path.read_text(encoding="utf-8")))
    digest = sha256_json(frozen)
    if (
        digest[:16] not in path.name
        or frozen["generator"] != generator_record()
        or frozen["baseline_sha256"] != sha256_json(baseline)
        or frozen["order_only"] != options.order_only
    ):
        raise ValueError("Frozen comparison identity differs")
    identity = require_object_dict(frozen["source_identity"])
    require_discovery_source_identity(context.paths, identity)
    by_id = {integer(hero["id"]): hero for hero in heroes}
    proposals = require_object_dict(frozen["heroes"])
    family = max(
        1,
        sum(
            len(require_object_rows(require_object_dict(value)["proposals"]))
            for value in proposals.values()
        ),
    )
    jobs = []
    for hero in baseline:
        hero_id = integer(hero["hero_id"])
        rows = require_object_rows(
            require_object_dict(proposals[str(hero_id)])["proposals"]
        )
        nominations = [
            BeamNomination(
                str(row["group"]),
                cast("NominatedCoreBuild", require_object_dict(row["row"])),
                {
                    str(key): float(str(value))
                    for key, value in require_object_dict(row["scores"]).items()
                },
            )
            for row in rows
        ]
        jobs.append(
            BeamValidationJob(
                BeamDiscoveryJob(by_id[hero_id], hero, context, options.order_only),
                BeamHeroProposals(nominations, []),
                family,
                digest,
            )
        )
    result = map_discovery_jobs(validate_beam_hero, jobs, options.workers)
    require_discovery_source_identity(context.paths, identity)
    return result
