"""Validate frozen beam proposals and preserve publication identities."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import TYPE_CHECKING

from deadlock_build_sync.artifacts import atomic_write_json
from deadlock_build_sync.build_support import numeric
from deadlock_build_sync.guide_generator import generator_record
from deadlock_build_sync.snapshot import sha256_json
from deadlock_build_sync.value_validation import (
    integer,
    require_object_dict,
    require_object_list,
)

from .beam_admission import complete_guide_rejection
from .beam_nomination import (
    BeamDiscoveryJob,
    BeamHeroProposals,
    BeamNomination,
    baseline_groups,
    core_items,
    discover_beam_hero,
)
from .beam_snapshot import beam_implementation_record
from .beam_support import core_state_statistics
from .core_discovery import calculate_core_identity
from .discovery_admission import admit_core
from .discovery_artifacts import build_evidence_payload
from .discovery_data import load_hero_discovery_data, prepare_discovery_partitions
from .discovery_export import _open_discovery_database
from .discovery_snapshot import (
    calculate_discovery_source_identity,
    require_discovery_source_identity,
)
from .discovery_workers import map_discovery_jobs

if TYPE_CHECKING:
    from .production_sources import _HeroExportContext


@dataclass(frozen=True)
class BeamValidationJob:
    discovery: BeamDiscoveryJob
    proposals: BeamHeroProposals
    family: int
    frozen_hash: str


def preferred_proposals(rows: list[BeamNomination]) -> list[BeamNomination]:
    ranked = sorted(
        rows,
        key=lambda row: (
            "1" not in row.scores,
            -row.scores.get("1", max(row.scores.values())),
            -row.row["discovery_support"],
            row.row["items"],
            row.row["path"]["order"],
        ),
    )
    unique: dict[str, BeamNomination] = {}
    for row in ranked:
        unique.setdefault(row.row["identity_id"], row)
    return list(unique.values())


def attach_group_metadata(
    members: list[dict[str, object]],
    group: str,
    default_variant: str,
    frozen_hash: str,
    rank_start: int,
) -> None:
    for index, build in enumerate(members):
        discovery = require_object_dict(build["discovery"])
        variant = calculate_core_identity(
            integer(discovery["hero_id"]), sorted(core_items(build))
        )
        build["path_id"] = group if index == 0 else variant + "-variant"
        build["guide_group_id"] = group
        metadata = require_object_dict(build["generator"])
        metadata.update({
            "group_id": group,
            "variant_id": variant,
            "default_variant_id": default_variant,
            "baseline_path_id": group,
            "core": sorted(core_items(build)),
            "frozen_sha256": frozen_hash,
        })
        build["generator"] = metadata
        discovery["selection_rank"] = rank_start + index
        build["discovery"] = discovery


def assemble_group(
    baseline: list[dict[str, object]],
    proposed: list[dict[str, object]],
    group: str,
    *,
    order_only: bool = False,
) -> list[dict[str, object]]:
    even = [
        build
        for build in proposed
        if 1 in require_object_list(require_object_dict(build["generator"])["states"])
    ]
    if even and not order_only:
        default = even[0]
        return [default, *(build for build in proposed if build is not default)]
    original = sorted(baseline, key=lambda build: build["path_id"] != group)
    fallback = copy.deepcopy(original)
    for build in fallback:
        build["generator"] = {
            "effective": "current",
            "states": [1],
            "fallback_reason": "No complete admitted even-state beam order for this core"
            if order_only
            else "No complete admitted even-state beam guide in this group",
        }
    if order_only:
        replacements = {core_items(build): build for build in even}
        return [replacements.get(core_items(build), build) for build in fallback]
    cores = {core_items(build) for build in fallback}
    return [*fallback, *(build for build in proposed if core_items(build) not in cores)]


def validate_beam_hero(job: BeamValidationJob) -> dict[str, object]:
    source = job.discovery
    context = source.context
    cohort = require_object_dict(source.baseline["cohort"])
    groups = baseline_groups(source.baseline)
    built: dict[str, list[dict[str, object]]] = {group: [] for group in groups}
    rejected: list[dict[str, object]] = []
    with _open_discovery_database(context) as connection:
        prepare_discovery_partitions(connection)
        values = load_hero_discovery_data(
            connection,
            integer(source.hero["id"]),
            context.item_graph,
            integer(cohort["minimum_badge"]),
            integer(cohort["maximum_badge"]),
        )
        for candidate in preferred_proposals(job.proposals.proposals):
            admitted = admit_core(values, candidate.row, job.family, job.frozen_hash)
            if admitted["rejections"]:
                rejected.append({
                    "variant": admitted["identity_id"],
                    "reasons": admitted["rejections"],
                })
                continue
            admitted["automatic_choices"] = {"version": 1, "branches": []}
            build = build_evidence_payload(
                connection, values, admitted, context.mechanics_assets_by_id
            )
            require_object_dict(build["discovery"])["method"] = "eclat_leiden_beam"
            failure = complete_guide_rejection(build, source, candidate.group)
            if failure:
                rejected.append({
                    "variant": admitted["identity_id"],
                    "reasons": [failure],
                })
                continue
            build["generator"] = {
                "effective": "beam",
                "states": sorted(int(state) for state in candidate.scores),
                "scores": candidate.scores,
                "state_evidence": {
                    state: core_state_statistics(
                        values, tuple(admitted["items"]), int(state)
                    )
                    for state in candidate.scores
                },
            }
            built[candidate.group].append(build)
        builds: list[dict[str, object]] = []
        for group, baseline in groups.items():
            proposed = built[group]
            proposed.sort(
                key=lambda build: (
                    "1"
                    not in require_object_dict(
                        require_object_dict(build["generator"])["scores"]
                    ),
                    -numeric(require_object_dict(build["discovery"]), "score"),
                    core_items(build)
                    != core_items(
                        next(row for row in baseline if row["path_id"] == group)
                    ),
                    -numeric(
                        require_object_dict(build["discovery"]), "discovery_support"
                    ),
                    str(build["path_id"]),
                )
            )
            members = assemble_group(
                baseline, proposed, group, order_only=source.order_only
            )
            for member in members:
                metadata = require_object_dict(member["generator"])
                if metadata["effective"] == "current":
                    metadata["state_evidence"] = {
                        "1": core_state_statistics(
                            values, tuple(sorted(core_items(member))), 1
                        )
                    }
                    member["generator"] = metadata
            default_variant = calculate_core_identity(
                values.hero, sorted(core_items(members[0]))
            )
            attach_group_metadata(
                members, group, default_variant, job.frozen_hash, len(builds)
            )
            builds.extend(members)
    print(f"Beam guides: {source.hero['name']} ({len(groups)} groups)", flush=True)
    return {**source.baseline, "builds": builds, "beam_rejections": rejected}


def generate_beam_roster(
    heroes: list[dict[str, object]],
    baseline: list[dict[str, object]],
    context: _HeroExportContext,
    *,
    workers: int,
    order_only: bool = False,
) -> list[dict[str, object]]:
    source_identity = calculate_discovery_source_identity(context.paths)
    by_id = {integer(hero["id"]): hero for hero in heroes}
    jobs = [
        BeamDiscoveryJob(by_id[integer(row["hero_id"])], row, context, order_only)
        for row in baseline
    ]
    proposals = map_discovery_jobs(discover_beam_hero, jobs, workers)
    frozen: dict[str, object] = {
        "generator": generator_record(),
        "implementation": beam_implementation_record(),
        "source_identity": source_identity,
        "baseline_sha256": sha256_json(baseline),
        "order_only": order_only,
        "heroes": {
            str(job.hero["id"]): {
                "proposals": [
                    {"group": row.group, "row": row.row, "scores": row.scores}
                    for row in result.proposals
                ],
                "groups": {
                    group: [sorted(core_items(build)) for build in builds]
                    for group, builds in baseline_groups(job.baseline).items()
                },
            }
            for job, result in zip(jobs, proposals, strict=True)
        },
    }
    digest = sha256_json(frozen)
    mode = "beam-order" if order_only else "beam"
    atomic_write_json(
        context.paths.run / f"{mode}-nominations-{digest[:16]}.json", frozen
    )
    atomic_write_json(
        context.paths.run / f"{mode}-diagnostics-{digest[:16]}.json",
        {
            str(job.hero["id"]): result.diagnostics
            for job, result in zip(jobs, proposals, strict=True)
        },
    )
    family = max(1, sum(len(result.proposals) for result in proposals))
    result = map_discovery_jobs(
        validate_beam_hero,
        [
            BeamValidationJob(job, proposed, family, digest)
            for job, proposed in zip(jobs, proposals, strict=True)
        ],
        workers,
    )
    require_discovery_source_identity(context.paths, source_identity)
    return result
