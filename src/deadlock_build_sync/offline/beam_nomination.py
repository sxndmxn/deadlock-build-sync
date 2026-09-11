"""Freeze supported beam proposals before validation outcomes are evaluated."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from deadlock_build_sync.build_support import SUPPORT
from deadlock_build_sync.mechanics import InventoryState, purchase_item
from deadlock_build_sync.value_validation import (
    integer,
    require_object_dict,
    require_object_list,
    require_object_rows,
)

from .beam_model import BeamItemModel, load_beam_model
from .beam_search import BeamRoute, GroupSearchRequest, search_group
from .beam_support import BeamOwnership
from .core_discovery import calculate_core_identity
from .discovery_artifacts import freeze_purchase_guide
from .discovery_data import load_hero_discovery_data, prepare_discovery_partitions
from .discovery_export import _open_discovery_database
from .discovery_orders import calculate_order_evidence, select_core_purchase_times
from .discovery_quality import evaluate_core
from .discovery_tactics import describe_mechanic_overlap
from .discovery_types import NominatedCoreBuild, SelectedPurchaseOrder

if TYPE_CHECKING:
    import duckdb

    from deadlock_build_sync.mechanics import ItemGraph

    from .discovery_data import HeroDiscoveryData
    from .production_sources import _HeroExportContext


@dataclass
class BeamNomination:
    group: str
    row: NominatedCoreBuild
    scores: dict[str, float]


@dataclass(frozen=True)
class BeamDiscoveryJob:
    hero: dict[str, object]
    baseline: dict[str, object]
    context: _HeroExportContext
    order_only: bool = False


@dataclass
class BeamHeroProposals:
    proposals: list[BeamNomination]
    diagnostics: list[dict[str, object]]


def baseline_groups(baseline: dict[str, object]) -> dict[str, list[dict[str, object]]]:
    groups: dict[str, list[dict[str, object]]] = {}
    for build in require_object_rows(baseline["builds"]):
        groups.setdefault(str(build["guide_group_id"]), []).append(build)
    return dict(
        sorted(
            groups.items(),
            key=lambda pair: min(
                integer(require_object_dict(build["discovery"])["selection_rank"])
                for build in pair[1]
            ),
        )
    )


def core_items(build: dict[str, object]) -> frozenset[int]:
    policy = require_object_dict(build["core_policy"])
    return frozenset(
        integer(item) for item in require_object_list(policy["default_item_ids"])
    )


def beam_purchase_order(
    values: HeroDiscoveryData, route: BeamRoute, graph: ItemGraph
) -> SelectedPurchaseOrder:
    order = [item for item in route.targets if item in route.core]
    evidence = {
        fold: calculate_order_evidence(
            select_core_purchase_times(values, list(route.core), fold),
            list(route.core),
            order,
        )
        for fold in ("discovery", "selection")
    }
    inventory = InventoryState()
    actions: list[dict[str, object]] = []
    spent = 0
    for item in route.path:
        credit = graph.credited_component_value(item, inventory.owned)
        cash = graph.incremental_cash_cost(item, inventory.owned)
        inventory = purchase_item(graph, inventory, item)
        spent += cash
        actions.append({
            "item_id": item,
            "name": graph.require(item).name,
            "role": "core" if item in route.core else "required_component",
            "component_credit": credit,
            "incremental_cost": cash,
            "cumulative_cost": spent,
            "owned_after": list(inventory.owned),
        })
    if set(inventory.owned) != set(route.core) or spent != route.spent:
        raise ValueError("Beam route differs from production mechanics replay")
    admitted = all(row["passes"] for row in evidence.values())
    return {
        "method": "beam16",
        "order": order,
        "discovery": evidence["discovery"],
        "selection": evidence["selection"],
        "admitted_before_validation": admitted,
        "legal": True,
        "actions": actions,
        "reason": None
        if admitted
        else "Beam order lacks discovery or selection support",
    }


def nominate_route(
    connection: duckdb.DuckDBPyConnection,
    job: BeamDiscoveryJob,
    values: HeroDiscoveryData,
    route: BeamRoute,
) -> tuple[NominatedCoreBuild | None, str | None]:
    graph = job.context.item_graph
    path = beam_purchase_order(values, route, graph)
    if not path["admitted_before_validation"]:
        return None, path["reason"]
    discovery = evaluate_core(values, route.core, "discovery")
    selection = evaluate_core(values, route.core, "selection")
    reasons = SUPPORT.core_reasons(discovery["owners"], selection["owners"])
    if reasons:
        return None, "; ".join(reasons)
    row: NominatedCoreBuild = {
        "items": list(route.core),
        "names": [graph.require(item).name for item in route.core],
        "identity_id": calculate_core_identity(values.hero, list(route.core)),
        "cost": sum(graph.require(item).cost for item in route.core),
        "score": route.score,
        "discovery_support": discovery["owners"],
        "discovery_lift": discovery["joint_lift"],
        "selection": selection,
        "selection_rejections": [],
        "selection_rank": 0,
        "hero_id": values.hero,
        "path": path,
        "branch_candidates": [],
        "tactics": describe_mechanic_overlap(
            job.hero, list(route.core), job.context.normal_assets
        ),
    }
    row["guide"] = freeze_purchase_guide(
        connection, values, row, graph, exact_path=route.path
    )
    if not row["guide"]["ready"]:
        return None, row["guide"].get("reason", "Incomplete beam guide")
    return row, None


def nominate_search(
    connection: duckdb.DuckDBPyConnection,
    job: BeamDiscoveryJob,
    values: HeroDiscoveryData,
    request: GroupSearchRequest,
    default: dict[str, object],
) -> BeamHeroProposals:
    if request.group is None:
        raise ValueError("Grouped nomination requires a group identifier")
    result = search_group(request)
    rejected: dict[str, int] = {}
    proposals: list[BeamNomination] = []
    accepted: set[tuple[int, ...]] = set()
    routes = sorted(
        result.routes,
        key=lambda route: (
            -route.score,
            frozenset(route.core) != core_items(default),
            -route.owners,
            route.core,
            route.path,
        ),
    )
    for route in routes:
        if route.core in accepted:
            continue
        row, reason = nominate_route(connection, job, values, route)
        if row is None:
            label = reason or "Unsupported beam route"
            rejected[label] = rejected.get(label, 0) + 1
            continue
        accepted.add(route.core)
        proposals.append(
            BeamNomination(request.group, row, {str(request.state): route.score})
        )
    return BeamHeroProposals(
        proposals,
        [
            {
                "group": request.group,
                "state": request.state,
                "routes": len(result.routes),
                "admitted_cores": len(accepted),
                "rejections": rejected,
                "unassigned": result.unassigned,
                "expansions": result.expansions,
                "search_seconds": result.elapsed_seconds,
            }
        ],
    )


def search_requests(
    job: BeamDiscoveryJob, values: HeroDiscoveryData, model: BeamItemModel
) -> list[tuple[GroupSearchRequest, dict[str, object]]]:
    grouped = baseline_groups(job.baseline)
    groups = {
        group: tuple(core_items(build) for build in builds)
        for group, builds in grouped.items()
    }
    requests = []
    for state in (1, 0, 2):
        ownership = BeamOwnership(values, job.context.item_graph, state)
        for group, builds in grouped.items():
            default = next(build for build in builds if build["path_id"] == group)
            request = GroupSearchRequest(
                job.context.item_graph,
                model,
                ownership,
                groups,
                group,
                state,
                values.items,
            )
            requests.extend(
                (candidate, default)
                for candidate in group_requests(
                    request, builds, order_only=job.order_only
                )
            )
    return requests


def group_requests(
    request: GroupSearchRequest, builds: list[dict[str, object]], *, order_only: bool
) -> list[GroupSearchRequest]:
    if not order_only:
        return [request]
    return [
        replace(
            request,
            candidates=tuple(sorted(core_items(build))),
            required_core=core_items(build),
        )
        for build in builds
    ]


def discover_beam_hero(job: BeamDiscoveryJob) -> BeamHeroProposals:
    cohort = require_object_dict(job.baseline["cohort"])
    minimum, maximum = (
        integer(cohort["minimum_badge"]),
        integer(cohort["maximum_badge"]),
    )
    proposals: dict[tuple[str, tuple[int, ...], tuple[int, ...]], BeamNomination] = {}
    diagnostics: list[dict[str, object]] = []
    with _open_discovery_database(job.context) as connection:
        prepare_discovery_partitions(connection)
        values = load_hero_discovery_data(
            connection,
            integer(job.hero["id"]),
            job.context.item_graph,
            minimum,
            maximum,
        )
        model = load_beam_model(connection, values, minimum, maximum)
        for request, default in search_requests(job, values, model):
            result = nominate_search(connection, job, values, request, default)
            diagnostics.extend(result.diagnostics)
            for proposed in result.proposals:
                key = (
                    proposed.group,
                    tuple(proposed.row["items"]),
                    tuple(proposed.row["guide"]["path"]),
                )
                nomination = proposals.setdefault(key, proposed)
                nomination.scores.update(proposed.scores)
    print(f"Beam proposals: {job.hero['name']} ({len(proposals)} routes)", flush=True)
    return BeamHeroProposals(list(proposals.values()), diagnostics)
