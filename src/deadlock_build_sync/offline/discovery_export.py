"""Export validated build evidence from Eclat, Leiden, and pairwise purchase ordering."""

from __future__ import annotations

import os
from dataclasses import dataclass

import duckdb
from threadpoolctl import threadpool_limits

from deadlock_build_sync.hero_cohort import HeroCohort, calculate_rank_cutoffs
from deadlock_build_sync.snapshot import sha256_json
from deadlock_build_sync.value_validation import integer, require_object_rows

from .core_discovery import discover_hero_cores
from .discovery_admission import admit_core
from .discovery_artifacts import build_evidence_payload, freeze_purchase_guide
from .discovery_branches import (
    BranchCandidateEvaluator,
    freeze_branch_candidates,
    load_checkpoint_rows,
)
from .discovery_data import (
    HeroDiscoveryData,
    load_hero_discovery_data,
    prepare_discovery_partitions,
)
from .discovery_guide_groups import assign_guide_group_ids
from .discovery_orders import select_purchase_order
from .discovery_snapshot import (
    calculate_discovery_source_identity,
    load_discovery_snapshot,
    require_discovery_source_identity,
    save_discovery_snapshot,
)
from .discovery_substitutions import (
    freeze_substitutions,
    select_validated_branch_candidates,
)
from .discovery_tactics import describe_mechanic_overlap
from .discovery_types import (
    DiscoveryItemCatalog,
    DiscoveryReport,
    FrozenHeroDiscovery,
    NominatedCoreBuild,
)
from .discovery_workers import map_discovery_jobs
from .production_sources import _HeroExportContext


@dataclass(frozen=True)
class ValidationFamily:
    cores: int
    branches: int
    frozen_hash: str


@dataclass(frozen=True)
class HeroDiscoveryJob:
    hero: dict[str, object]
    context: _HeroExportContext
    catalog: DiscoveryItemCatalog


@dataclass(frozen=True)
class HeroValidationJob:
    hero: dict[str, object]
    context: _HeroExportContext
    report: FrozenHeroDiscovery
    family: ValidationFamily
    groups: dict[str, str]


def discover_hero_roster(
    heroes: list[dict[str, object]],
    context: _HeroExportContext,
    *,
    workers: int = 8,
    resume: bool = False,
) -> list[dict[str, object]]:
    source_identity = calculate_discovery_source_identity(context.paths)
    graph = context.item_graph
    catalog: DiscoveryItemCatalog = {
        str(item): {
            "name": node.name,
            "cost": node.cost,
            "ancestors": list(graph.transitive_components(item)),
        }
        for item, node in graph.nodes.items()
    }
    print(f"Processing heroes with {workers} CPU workers", flush=True)
    if resume:
        frozen, guide_groups = load_discovery_snapshot(context.paths, heroes)
    else:
        reports = map_discovery_jobs(
            _run_discovery_job,
            [HeroDiscoveryJob(hero, context, catalog) for hero in heroes],
            workers,
        )
        frozen = {
            integer(hero["id"]): report
            for hero, report in zip(heroes, reports, strict=True)
        }
        guide_groups = {
            hero: assign_guide_group_ids(report["rows"])
            for hero, report in frozen.items()
        }
        # Save the entire family before accessing any validation outcome.
        save_discovery_snapshot(context.paths, frozen, guide_groups, source_identity)
    family = ValidationFamily(
        max(1, sum(len(value["rows"]) for value in frozen.values())),
        max(
            1,
            sum(
                len(row["branch_candidates"])
                for value in frozen.values()
                for row in value["rows"]
            ),
        ),
        sha256_json(frozen),
    )
    results = map_discovery_jobs(
        _run_validation_job,
        [
            HeroValidationJob(
                hero,
                context,
                frozen[integer(hero["id"])],
                family,
                guide_groups[integer(hero["id"])],
            )
            for hero in heroes
        ],
        workers,
    )
    require_discovery_source_identity(context.paths, source_identity)
    return results


def _open_discovery_database(context: _HeroExportContext) -> duckdb.DuckDBPyConnection:
    spill_directory = context.paths.run / "duckdb-workers" / str(os.getpid())
    spill_directory.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(
        str(context.paths.raw / "analysis.duckdb"),
        read_only=True,
        config={
            "threads": 1,
            "memory_limit": "512MiB",
            "temp_directory": str(spill_directory),
        },
    )


def _run_discovery_job(job: HeroDiscoveryJob) -> FrozenHeroDiscovery:
    with (
        _open_discovery_database(job.context) as connection,
        threadpool_limits(limits=1),
    ):
        prepare_discovery_partitions(connection)
        _, report = _freeze_hero(connection, job.hero, job.context, job.catalog)
        return report


def _run_validation_job(job: HeroValidationJob) -> dict[str, object]:
    with (
        _open_discovery_database(job.context) as connection,
        threadpool_limits(limits=1),
    ):
        prepare_discovery_partitions(connection)
        cohort = job.report["cohort"]
        values = load_hero_discovery_data(
            connection,
            integer(job.hero["id"]),
            job.context.item_graph,
            integer(cohort["minimum_badge"]),
            integer(cohort["maximum_badge"]),
        )
        print(f"Validating {job.hero['name']}", flush=True)
        result = _validate_hero(
            connection, job.hero, (values, job.report), job.context, job.family
        )
        for build in require_object_rows(result["builds"]):
            build["guide_group_id"] = job.groups[str(build["path_id"])]
        print(f"Validated {job.hero['name']}", flush=True)
        return result


def _freeze_hero(
    connection: duckdb.DuckDBPyConnection,
    hero: dict[str, object],
    context: _HeroExportContext,
    catalog: DiscoveryItemCatalog,
) -> tuple[HeroDiscoveryData, FrozenHeroDiscovery]:
    hero_id, graph = integer(hero["id"]), context.item_graph
    print(f"Discovering {hero['name']}", flush=True)
    history: list[dict[str, object]] = []
    cutoffs = iter(
        calculate_rank_cutoffs(
            context.minimum_badge, context.maximum_badge, context.rank_expansion
        )
    )
    minimum = next(cutoffs)
    while True:
        values = load_hero_discovery_data(
            connection, hero_id, graph, minimum, context.maximum_badge
        )
        report = discover_hero_cores(values, catalog)
        rows = _select_usable_build_identities(
            connection, hero, values, report, context
        )
        candidates = list(report["candidates"])
        if not rows:
            report = discover_hero_cores(values, catalog, seeds=report["seeds"])
            candidates.extend(report["candidates"])
            rows = _select_usable_build_identities(
                connection, hero, values, report, context
            )
        history.append({
            "minimum_badge": minimum,
            "maximum_badge": context.maximum_badge,
            "discovery_rows": int(values.fold_mask("discovery").sum()),
            "selection_rows": int(values.fold_mask("selection").sum()),
            "candidate_count": len(candidates),
            "discovery_owners": max(
                (row["discovery_support"] for row in candidates), default=0
            ),
            "selection_owners": max(
                (row["selection"]["owners"] for row in candidates), default=0
            ),
            "supported_builds": len(rows),
            "reason": "supported build available"
            if rows
            else "no supported legal path",
        })
        following = next(cutoffs, None)
        if rows or following is None:
            break
        minimum = following
    decisions = (
        load_checkpoint_rows(connection, hero_id, graph, minimum, context.maximum_badge)
        if rows
        else []
    )
    for row in rows:
        row["branch_candidates"] = freeze_branch_candidates(decisions, row, graph)
    freeze_substitutions(decisions, rows, graph)
    frozen: FrozenHeroDiscovery = {
        "rows": rows,
        "candidate_count": len(candidates),
        "grouping": report["grouping"],
        "candidates": candidates,
        "cohort": HeroCohort(
            minimum, context.maximum_badge, context.rank_expansion, tuple(history)
        ).as_dict(),
    }
    print(f"Discovered {hero['name']} ({len(rows)} build candidates)", flush=True)
    return values, frozen


def _select_usable_build_identities(
    connection: duckdb.DuckDBPyConnection,
    hero: dict[str, object],
    values: HeroDiscoveryData,
    report: DiscoveryReport,
    context: _HeroExportContext,
) -> list[NominatedCoreBuild]:
    membership = {
        index: group
        for group, indices in enumerate(report["grouping"]["groups"])
        for index in indices
    }
    used: set[int] = set()
    rows: list[NominatedCoreBuild] = []
    for rank, index in enumerate(report["selected"]["grouped_pairwise"]):
        if membership[index] in used:
            continue
        candidate = report["candidates"][index]
        row: NominatedCoreBuild = {
            **candidate,
            "selection_rank": rank,
            "hero_id": values.hero,
            "path": select_purchase_order(
                values, candidate["items"], "pairwise", context.item_graph
            ),
        }
        if not row["path"]["admitted_before_validation"]:
            candidate["selection_rejections"].append(
                row["path"]["reason"] or "No supported legal path"
            )
            continue
        row["guide"] = freeze_purchase_guide(
            connection, values, row, context.item_graph
        )
        if not row["guide"]["ready"]:
            candidate["selection_rejections"].append(
                row["guide"]["reason"] or "Incomplete purchase records"
            )
            continue
        row["tactics"] = describe_mechanic_overlap(
            hero, row["items"], context.normal_assets
        )
        rows.append(row)
        used.add(membership[index])
    return rows


def _validate_hero(
    connection: duckdb.DuckDBPyConnection,
    hero: dict[str, object],
    entry: tuple[HeroDiscoveryData, FrozenHeroDiscovery],
    context: _HeroExportContext,
    family: ValidationFamily,
) -> dict[str, object]:
    values, report = entry
    hero_id, graph = integer(hero["id"]), context.item_graph
    builds, rejections = [], []
    reviewed = [
        admit_core(values, row, family.cores, family.frozen_hash)
        for row in report["rows"]
    ]
    cohort = report["cohort"]
    decisions = (
        load_checkpoint_rows(
            connection,
            hero_id,
            graph,
            integer(cohort["minimum_badge"]),
            integer(cohort["maximum_badge"]),
        )
        if any(not row["rejections"] and row["branch_candidates"] for row in reviewed)
        else []
    )
    evaluator = BranchCandidateEvaluator(decisions, graph, family.branches)
    for admitted in reviewed:
        reasons = admitted["rejections"]
        if reasons:
            rejections.append({
                "path_id": admitted["identity_id"],
                "reasons": reasons,
            })
        else:
            admitted["automatic_choices"] = evaluator.evaluate_candidates(
                admitted,
                select_validated_branch_candidates(admitted, reviewed),
            )
            builds.append(
                build_evidence_payload(
                    connection, values, admitted, context.mechanics_assets_by_id
                )
            )
    print(
        f"{hero['name']}: {evaluator.contrast_cache.calculated_fits} branch fits, "
        f"{evaluator.contrast_cache.reused_fits} identical fits reused",
        flush=True,
    )
    exclusion = (
        None
        if builds
        else {
            "code": "no_validated_identity",
            "reason": "No supported legal build in the attempted rank ranges",
            "candidate_count": report["candidate_count"],
            "fold_observations": {
                fold: int(values.fold_mask(fold).sum())
                for fold in ("discovery", "selection", "validation")
            },
            "candidate_rejections": rejections
            or [
                {"items": row["items"], "reasons": row["selection_rejections"]}
                for row in report["candidates"]
            ],
        }
    )
    return {
        "cohort": report["cohort"],
        "hero_id": hero_id,
        "hero": hero["name"],
        "builds": builds,
        "exclusion": exclusion,
        "path_abstentions": rejections,
    }
