"""Check grouped search, ownership support, and component accounting."""

from dataclasses import replace
from itertools import product

import numpy as np
import pytest

from deadlock_build_sync.build_support import numeric
from deadlock_build_sync.mechanics import ItemGraph
from deadlock_build_sync.offline.beam_model import BeamItemModel
from deadlock_build_sync.offline.beam_nomination import beam_purchase_order
from deadlock_build_sync.offline.beam_search import (
    BeamRoute,
    GroupSearchRequest,
    extend_route,
    search_group,
    terminal_route,
)
from deadlock_build_sync.offline.beam_support import (
    BeamOwnership,
    assign_core_group,
    core_state_statistics,
    wealth_state,
)
from deadlock_build_sync.offline.discovery_data import HeroDiscoveryData
from deadlock_build_sync.value_validation import require_object_dict
from tests.offline.discovery_fixtures import make_hero_discovery_data, make_item_graph


def make_beam_values() -> HeroDiscoveryData:
    values = make_hero_discovery_data()
    values.inventories = tuple(
        tuple(int(item) for item in np.flatnonzero(row)) for row in values.matrix
    )
    return values


def make_beam_model(graph: ItemGraph) -> BeamItemModel:
    return BeamItemModel(
        [
            (wealth, state, item, 1000, 600)
            for wealth, state, item in product(range(12), range(3), graph.nodes)
        ],
        600,
        1000,
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0.89, 0), (0.9, 1), (1.1, 1), (1.11, 2), (np.nan, None), (np.inf, None)],
)
def test_wealth_boundaries_and_missing_data(value: float, expected: int | None) -> None:
    assert wealth_state(value) == expected


def test_group_membership_requires_every_member_and_unique_assignment() -> None:
    groups = {
        "weapon": (frozenset((1, 2, 3, 4)), frozenset((1, 2, 3, 5))),
        "spirit": (frozenset((6, 7, 8, 9)),),
    }
    assert assign_core_group(frozenset((1, 2, 3, 10)), groups) == "weapon"
    assert assign_core_group(frozenset((1, 2, 4, 10)), groups) is None
    assert assign_core_group(frozenset((1, 2, 3, 4)), groups) == "weapon"
    ambiguous: dict[str, tuple[frozenset[int], ...]] = {
        "first": (frozenset((1, 2, 3, 4)),),
        "second": (frozenset((1, 2, 3, 5)),),
    }
    assert assign_core_group(frozenset((1, 2, 3, 6)), ambiguous) is None
    assert assign_core_group(frozenset((1, 2)), {}) is None


def test_grouped_search_returns_supported_complete_deterministic_cores() -> None:
    graph, values = make_item_graph(13), make_beam_values()
    request = GroupSearchRequest(
        graph,
        make_beam_model(graph),
        BeamOwnership(values, graph, 1),
        {"first": (frozenset(range(4)),)},
        "first",
        1,
        tuple(range(13)),
    )
    first, second = search_group(request), search_group(request)
    assert first.routes
    assert first.routes == second.routes
    assert all(len(route.core) >= 4 and route.owners >= 200 for route in first.routes)
    assert any(
        beam_purchase_order(values, route, graph)["admitted_before_validation"]
        for route in first.routes
    )
    assert not search_group(
        replace(request, ownership=BeamOwnership(values, graph, 0), state=0)
    ).routes
    assert not search_group(replace(request, candidates=())).routes


def test_order_control_preserves_exact_core() -> None:
    graph, values = make_item_graph(13), make_beam_values()
    core = frozenset(range(4))
    request = GroupSearchRequest(
        graph,
        make_beam_model(graph),
        BeamOwnership(values, graph, 1),
        {"first": (core,)},
        "first",
        1,
        tuple(range(5)),
        core,
    )
    result = search_group(request)
    assert result.routes and all(
        frozenset(route.core) == core for route in result.routes
    )
    assert terminal_route(request, BeamRoute(core=(0, 1))) is None
    assert terminal_route(request, BeamRoute(core=(4, 5, 6, 7))) is None
    assert terminal_route(request, BeamRoute(core=(0, 1, 2, 3, 12))) is None


def test_pure_beam_does_not_call_group_assignment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reject_group_assignment(*_args: object) -> None:
        pytest.fail("Pure beam must not use frozen group assignment")

    monkeypatch.setattr(
        "deadlock_build_sync.offline.beam_search.assign_core_group",
        reject_group_assignment,
    )
    graph, values = make_item_graph(13), make_beam_values()
    request = GroupSearchRequest(
        graph,
        make_beam_model(graph),
        BeamOwnership(values, graph, 1),
        {},
        None,
        1,
        tuple(range(13)),
    )
    result = search_group(request)
    assert result.routes
    assert result.unassigned == 0
    assert all(4 <= len(route.core) <= 6 for route in result.routes)
    assert terminal_route(request, BeamRoute(core=(0, 1, 2))) is None


def test_components_can_be_bought_again_for_a_second_upgrade() -> None:
    base = make_item_graph(7)
    nodes = dict(base.nodes)
    nodes[0] = replace(nodes[0], cost=800, tier=1)
    nodes[1] = replace(nodes[1], component_classes=(nodes[0].class_name,))
    nodes[2] = replace(nodes[2], component_classes=(nodes[0].class_name,))
    graph = ItemGraph(nodes)
    model = make_beam_model(graph)
    first = extend_route(graph, model, BeamRoute(), 1, 1)
    assert first is not None and first.path == (0, 1)
    second = extend_route(graph, model, first, 2, 1)
    assert second is not None and second.path == (0, 1, 0, 2)
    assert second.core == (1, 2) and second.spent == 3200
    assert second.cash == 0 and second.net_worth == 3200
    assert extend_route(graph, model, second, 2, 1) is None


def test_search_rejects_budget_active_and_support_failures() -> None:
    graph = make_item_graph(10, active=True)
    model = make_beam_model(graph)
    assert extend_route(graph, model, BeamRoute(core=(0, 1, 2, 3)), 4, 1) is None
    assert extend_route(graph, model, BeamRoute(spent=19000), 1, 1) is None
    assert extend_route(graph, BeamItemModel([], 0, 0), BeamRoute(), 1, 1) is None
    assert (
        extend_route(make_item_graph(10), model, BeamRoute(core=tuple(range(6))), 6, 1)
        is None
    )


def test_complete_core_statistics_do_not_sum_item_counts() -> None:
    values, graph = make_beam_values(), make_item_graph(13)
    ownership = BeamOwnership(values, graph, 1)
    assert ownership.count((0, 1, 2, 3)) == 400
    assert ownership.count((0, 4)) == 0
    result = core_state_statistics(values, (0, 1, 2, 3), 1)
    assert require_object_dict(result["discovery"])["owners"] == 400
    assert (
        numeric(require_object_dict(result["discovery"]), "lower_95")
        < numeric(require_object_dict(result["discovery"]), "win_rate")
        < numeric(require_object_dict(result["discovery"]), "upper_95")
    )
    assert (
        require_object_dict(core_state_statistics(values, (0, 1), 0)["discovery"])[
            "win_rate"
        ]
        is None
    )


def test_bayesian_smoothing_and_state_cells_remain_separate() -> None:
    model = BeamItemModel([(0, 0, 1, 30, 30), (0, 1, 1, 1000, 500)], 500, 1000)
    assert model.estimate(0, 0, 1) != model.estimate(0, 1, 1)
    assert model.estimate(0, 2, 1)[1] == 0
    assert model.score(0, 2, 1, 800, 0) is None
    assert model.estimate(0, 0, 1)[0] < 0.5


def test_mechanics_replay_rejects_inconsistent_recorded_cost() -> None:
    graph = make_item_graph(13)
    with pytest.raises(ValueError, match="production mechanics replay"):
        beam_purchase_order(
            make_beam_values(),
            BeamRoute(
                core=(0, 1, 2, 3), targets=(0, 1, 2, 3), path=(0, 1, 2, 3), spent=1
            ),
            graph,
        )
