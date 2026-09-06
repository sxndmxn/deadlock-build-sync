"""Eclat -> Leiden -> pairwise is the only normal evidence producer."""

from __future__ import annotations

import json

import duckdb
from threadpoolctl import threadpool_limits

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
from .discovery_types import Catalog, FrozenHero, Nomination
from .production_sources import _HeroExportContext


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
                data[hero_id],
                frozen[hero_id],
                context,
                family,
                branch_family,
                sha256_json(frozen),
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
    values = load_data(con, hero_id, graph)
    report = discover_hero(values, catalog)
    decisions = (
        checkpoint_rows(con, hero_id, graph)
        if report["selected"]["grouped_pairwise"]
        else []
    )
    rows: list[Nomination] = []
    for rank, index in enumerate(report["selected"]["grouped_pairwise"]):
        row: Nomination = {
            **report["candidates"][index],
            "selection_rank": rank,
            "hero_id": hero_id,
            "path": choose_order(
                values,
                report["candidates"][index]["items"],
                "pairwise",
                graph,
            ),
        }
        row["tactics"] = explain(hero, row["items"], context.normal_assets)
        row["guide"] = freeze_guide(con, values, row, graph)
        row["branch_candidates"] = freeze_candidates(decisions, row, graph)
        rows.append(row)
    freeze_substitutions(decisions, rows, graph)
    frozen: FrozenHero = {
        "rows": rows,
        "candidate_count": len(report["candidates"]),
        "grouping": report["grouping"],
        "candidates": report["candidates"],
    }
    return values, frozen


def _validate_hero(
    con: duckdb.DuckDBPyConnection,
    hero: dict[str, object],
    values: HeroData,
    report: FrozenHero,
    context: _HeroExportContext,
    family: int,
    branch_family: int,
    frozen_hash: str,
) -> dict[str, object]:
    hero_id, graph = integer(hero["id"]), context.item_graph
    builds, rejections = [], []
    reviewed = [admit_core(values, row, family, frozen_hash) for row in report["rows"]]
    decisions = (
        checkpoint_rows(con, hero_id, graph)
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
                branch_family,
            )
            builds.append(
                build_payload(con, values, admitted, context.mechanics_assets_by_id)
            )
    exclusion = (
        None
        if builds
        else {
            "code": "no_validated_identity",
            "reason": "No identity passed discovery, selection, core outcome, purchase order, mechanics, and pool checks",
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
        "hero_id": hero_id,
        "hero": hero["name"],
        "builds": builds,
        "exclusion": exclusion,
        "path_abstentions": rejections,
    }
