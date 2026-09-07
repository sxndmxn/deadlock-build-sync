"""Eclat -> Leiden -> pairwise is the only normal evidence producer."""

from __future__ import annotations

import json
from dataclasses import dataclass

import duckdb
from threadpoolctl import threadpool_limits

from deadlock_build_sync.hero_cohort import HeroCohort, ranked_cutoffs
from deadlock_build_sync.snapshot import sha256_json
from deadlock_build_sync.value_validation import integer

from .discovery_admission import admit_core
from .discovery_branches import checkpoint_rows, evaluate_candidates, freeze_candidates
from .discovery_data import HeroData, load_data, prepare_partitions
from .discovery_fit import discover_hero
from .discovery_materialize import build_payload, freeze_guide
from .discovery_orders import choose_order
from .discovery_substitutions import freeze_substitutions, validated_candidates
from .discovery_tactics import explain
from .discovery_types import Catalog, DiscoveryReport, FrozenHero, Nomination
from .production_sources import _HeroExportContext


@dataclass(frozen=True)
class ValidationFamily:
    cores: int
    branches: int
    frozen_hash: str


def discover_roster(
    heroes: list[dict[str, object]], context: _HeroExportContext
) -> list[dict[str, object]]:
    con = duckdb.connect(str(context.paths.raw / "analysis.duckdb"), read_only=True)
    con.execute("SET threads=2")
    graph = context.item_graph
    catalog: Catalog = {
        str(item): {
            "name": node.name,
            "cost": node.cost,
            "ancestors": list(graph.transitive_components(item)),
        }
        for item, node in graph.nodes.items()
    }
    frozen: dict[int, FrozenHero] = {}
    data: dict[int, HeroData] = {}
    try:
        prepare_partitions(con)
        with threadpool_limits(limits=1):
            for hero in heroes:
                hero_id = integer(hero["id"])
                data[hero_id], frozen[hero_id] = _freeze_hero(
                    con, hero, context, catalog
                )
        # Save the entire family before accessing any validation outcome.
        frozen_path = (
            context.paths.run / f"discovery-nominations-{sha256_json(frozen)[:16]}.json"
        )
        frozen_path.write_text(json.dumps(frozen, allow_nan=False), encoding="utf-8")
        family = max(1, sum(len(value["rows"]) for value in frozen.values()))
        branch_family = max(
            1,
            sum(
                len(row["branch_candidates"])
                for value in frozen.values()
                for row in value["rows"]
            ),
        )
        output = []
        for hero in heroes:
            hero_id = integer(hero["id"])
            result = _validate_hero(
                con,
                hero,
                (data[hero_id], frozen[hero_id]),
                context,
                ValidationFamily(family, branch_family, sha256_json(frozen)),
            )
            output.append(result)
            print(f"Validated {hero['name']}", flush=True)
        return output
    finally:
        con.close()


def _freeze_hero(
    con: duckdb.DuckDBPyConnection,
    hero: dict[str, object],
    context: _HeroExportContext,
    catalog: Catalog,
) -> tuple[HeroData, FrozenHero]:
    hero_id, graph = integer(hero["id"]), context.item_graph
    print(f"Discovering {hero['name']}", flush=True)
    history: list[dict[str, object]] = []
    cutoffs = iter(
        ranked_cutoffs(
            context.minimum_badge, context.maximum_badge, context.rank_expansion
        )
    )
    minimum = next(cutoffs)
    while True:
        values = load_data(con, hero_id, graph, minimum, context.maximum_badge)
        report = discover_hero(values, catalog)
        rows = _usable_identities(con, hero, values, report, context)
        candidates = list(report["candidates"])
        if not rows:
            report = discover_hero(values, catalog, seeds=report["seeds"])
            candidates.extend(report["candidates"])
            rows = _usable_identities(con, hero, values, report, context)
        history.append({
            "minimum_badge": minimum,
            "maximum_badge": context.maximum_badge,
            "discovery_rows": int(values.mask("discovery").sum()),
            "selection_rows": int(values.mask("selection").sum()),
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
        checkpoint_rows(con, hero_id, graph, minimum, context.maximum_badge)
        if rows
        else []
    )
    for row in rows:
        row["branch_candidates"] = freeze_candidates(decisions, row, graph)
    freeze_substitutions(decisions, rows, graph)
    frozen: FrozenHero = {
        "rows": rows,
        "candidate_count": len(candidates),
        "grouping": report["grouping"],
        "candidates": candidates,
        "cohort": HeroCohort(
            minimum, context.maximum_badge, context.rank_expansion, tuple(history)
        ).as_dict(),
    }
    return values, frozen


def _usable_identities(
    con: duckdb.DuckDBPyConnection,
    hero: dict[str, object],
    values: HeroData,
    report: DiscoveryReport,
    context: _HeroExportContext,
) -> list[Nomination]:
    membership = {
        index: group
        for group, indices in enumerate(report["grouping"]["groups"])
        for index in indices
    }
    used: set[int] = set()
    rows: list[Nomination] = []
    for rank, index in enumerate(report["selected"]["grouped_pairwise"]):
        if membership[index] in used:
            continue
        candidate = report["candidates"][index]
        row: Nomination = {
            **candidate,
            "selection_rank": rank,
            "hero_id": values.hero,
            "path": choose_order(
                values, candidate["items"], "pairwise", context.item_graph
            ),
        }
        if not row["path"]["admitted_before_validation"]:
            candidate["selection_rejections"].append(
                row["path"]["reason"] or "No supported legal path"
            )
            continue
        row["guide"] = freeze_guide(con, values, row, context.item_graph)
        if not row["guide"]["ready"]:
            candidate["selection_rejections"].append(
                row["guide"]["reason"] or "Incomplete purchase records"
            )
            continue
        row["tactics"] = explain(hero, row["items"], context.normal_assets)
        rows.append(row)
        used.add(membership[index])
    return rows


def _validate_hero(
    con: duckdb.DuckDBPyConnection,
    hero: dict[str, object],
    entry: tuple[HeroData, FrozenHero],
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
        checkpoint_rows(
            con,
            hero_id,
            graph,
            integer(cohort["minimum_badge"]),
            integer(cohort["maximum_badge"]),
        )
        if any(not row["rejections"] and row["branch_candidates"] for row in reviewed)
        else []
    )
    for admitted in reviewed:
        reasons = admitted["rejections"]
        if reasons:
            rejections.append({
                "path_id": admitted["identity_id"],
                "reasons": reasons,
            })
        else:
            admitted["automatic_choices"] = evaluate_candidates(
                decisions,
                admitted,
                validated_candidates(admitted, reviewed),
                graph,
                family.branches,
            )
            builds.append(
                build_payload(con, values, admitted, context.mechanics_assets_by_id)
            )
    exclusion = (
        None
        if builds
        else {
            "code": "no_validated_identity",
            "reason": "No supported legal build in the attempted rank ranges",
            "candidate_count": report["candidate_count"],
            "fold_observations": {
                fold: int(values.mask(fold).sum())
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
