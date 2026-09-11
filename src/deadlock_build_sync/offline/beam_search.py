"""Search complete purchase routes with optional frozen-group restrictions."""

from __future__ import annotations

import time
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from deadlock_build_sync.guide_generator import BEAM_SETTINGS
from deadlock_build_sync.mechanics import MechanicsError
from deadlock_build_sync.purchase_planner import PurchasePlanner

from .beam_support import assign_core_group

if TYPE_CHECKING:
    from deadlock_build_sync.mechanics import ItemGraph

    from .beam_model import BeamItemModel
    from .beam_support import BeamOwnership


@dataclass(frozen=True)
class BeamRoute:
    core: tuple[int, ...] = ()
    targets: tuple[int, ...] = ()
    path: tuple[int, ...] = ()
    score: float = 0.0
    spent: int = 0
    net_worth: int = 800
    cash: int = 800
    owners: int = 0


@dataclass(frozen=True)
class GroupSearchResult:
    routes: tuple[BeamRoute, ...]
    expansions: int
    elapsed_seconds: float
    unassigned: int


def extend_route(
    graph: ItemGraph, model: BeamItemModel, route: BeamRoute, item: int, state: int
) -> BeamRoute | None:
    if item in route.targets or item in route.core:
        return None
    planner = PurchasePlanner(graph, route.core, 0)
    try:
        planner.add_item_purchases(item, exact=True)
    except MechanicsError:
        return None
    spent = route.spent + planner.total_cost
    if spent > BEAM_SETTINGS["maximum_core_cost"] or len(planner.state.owned) > 6:
        return None
    score, wealth, cash = route.score, route.net_worth, route.cash
    for index, step in enumerate(planner.actions, len(route.path)):
        income = max(0, step.incremental_cost - cash)
        wealth += income
        cash = max(0, cash - step.incremental_cost)
        value = model.score(wealth, state, step.item_id, step.incremental_cost, index)
        if value is None:
            return None
        score += value
    return BeamRoute(
        tuple(sorted(planner.state.owned)),
        (*route.targets, item),
        (*route.path, *(step.item_id for step in planner.actions)),
        score,
        spent,
        wealth,
        cash,
    )


@dataclass(frozen=True)
class GroupSearchRequest:
    graph: ItemGraph
    model: BeamItemModel
    ownership: BeamOwnership
    groups: dict[str, tuple[frozenset[int], ...]]
    group: str | None
    state: int
    candidates: tuple[int, ...]
    required_core: frozenset[int] | None = None


def minimum_core_size(request: GroupSearchRequest) -> int:
    if request.group is None:
        return 4
    return 3 if min(map(len, request.groups[request.group])) == 3 else 4


def terminal_route(request: GroupSearchRequest, route: BeamRoute) -> BeamRoute | None:
    minimum = minimum_core_size(request)
    if len(route.core) < minimum:
        return None
    if request.group is not None and (
        assign_core_group(frozenset(route.core), request.groups) != request.group
    ):
        return None
    if (
        request.required_core is not None
        and frozenset(route.core) != request.required_core
    ):
        return None
    count = request.ownership.count(route.core)
    if count < BEAM_SETTINGS["minimum_core_support"]:
        return None
    return replace(route, owners=count)


def expand_frontier(
    request: GroupSearchRequest, frontier: list[BeamRoute]
) -> tuple[list[BeamRoute], list[BeamRoute], int, int]:
    following: dict[tuple[tuple[int, ...], tuple[int, ...]], BeamRoute] = {}
    completed: list[BeamRoute] = []
    expansions = 0
    unassigned = 0
    anchors = (
        frozenset(request.candidates)
        if request.group is None
        else frozenset().union(*request.groups[request.group])
    )
    for route in frontier:
        for item in request.candidates:
            if not route.targets and item not in anchors:
                continue
            expansions += 1
            child = extend_route(
                request.graph, request.model, route, item, request.state
            )
            if (
                child is None
                or request.ownership.count(child.core, expanded=True)
                < BEAM_SETTINGS["minimum_core_support"]
            ):
                continue
            identity = child.core, tuple(sorted(child.targets))
            previous = following.get(identity)
            if previous is None or (-child.score, child.path) < (
                -previous.score,
                previous.path,
            ):
                following[identity] = child
            terminal = terminal_route(request, child)
            if terminal is not None:
                completed.append(terminal)
            elif is_unassigned_terminal(request, child):
                unassigned += 1
    return list(following.values()), completed, expansions, unassigned


def is_unassigned_terminal(request: GroupSearchRequest, route: BeamRoute) -> bool:
    if request.group is None:
        return False
    minimum = minimum_core_size(request)
    return (
        len(route.core) >= minimum
        and request.ownership.count(route.core) >= BEAM_SETTINGS["minimum_core_support"]
        and assign_core_group(frozenset(route.core), request.groups) is None
    )


def search_group(request: GroupSearchRequest) -> GroupSearchResult:
    started = time.monotonic()
    maximum_depth = 6 * max(
        (
            1 + len(request.graph.transitive_components(item))
            for item in request.candidates
        ),
        default=1,
    )
    frontier = [BeamRoute()]
    terminal: dict[tuple[tuple[int, ...], tuple[int, ...]], BeamRoute] = {}
    expansions = 0
    unassigned = 0
    for _depth in range(maximum_depth):
        following, completed, count, rejected = expand_frontier(request, frontier)
        expansions += count
        unassigned += rejected
        for route in completed:
            terminal[route.core, route.path] = route
        frontier = sorted(following, key=lambda row: (-row.score, row.path))[
            : int(BEAM_SETTINGS["width"])
        ]
        if not frontier:
            break
    return GroupSearchResult(
        tuple(
            sorted(
                terminal.values(),
                key=lambda row: (-row.score, -row.owners, row.core, row.path),
            )
        ),
        expansions,
        time.monotonic() - started,
        unassigned,
    )
