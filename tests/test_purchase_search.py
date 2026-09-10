"""Check purchase-search mechanics and small exact search cases."""

from __future__ import annotations

from dataclasses import replace
from itertools import product

import pytest

from deadlock_build_sync.mechanics import ItemGraph
from deadlock_build_sync.mechanics_items import ItemNode
from tools.purchase_search.model import ItemModel
from tools.purchase_search.records import (
    Catalog,
    Query,
    ScoringConfig,
    SearchConfig,
    SearchState,
)
from tools.purchase_search.search import (
    distinct_states,
    inventory_distance,
    retain_diverse,
    search,
    select_final,
    transition,
    validate_path,
)


def catalog_fixture() -> Catalog:
    nodes = {
        1: ItemNode(
            1,
            "item_a",
            "First Item",
            800,
            "weapon",
            1,
            (),
            active=False,
            unique=True,
            max_count=1,
        ),
        2: ItemNode(
            2,
            "item_b",
            "Component Item",
            800,
            "spirit",
            1,
            (),
            active=False,
            unique=True,
            max_count=1,
        ),
        3: ItemNode(
            3,
            "item_c",
            "Upgrade Item",
            1600,
            "spirit",
            2,
            ("item_b",),
            active=False,
            unique=True,
            max_count=1,
        ),
    }
    return Catalog.from_graph(ItemGraph(nodes))


def model_fixture(
    catalog: Catalog,
    rates: tuple[float, ...] = (0.65, 0.60, 0.78),
    config: ScoringConfig | None = None,
) -> ItemModel:
    statistics = {
        "partition": "train",
        "patch": "test-patch",
        "fingerprint": "test-data",
        "hero_counts": [[1, 1000, 500]],
        "item_ids": list(catalog.item_ids),
        "item_counts": [
            [1, wealth, relative, item, 1000, round(1000 * rates[index])]
            for wealth, relative, (index, item) in product(
                range(12), range(3), enumerate(catalog.item_ids)
            )
        ],
        "state_counts": [
            [1, wealth, relative, 1000, 500]
            for wealth, relative in product(range(12), range(3))
        ],
    }
    return ItemModel(statistics, config or ScoringConfig(1, 0, 1, 1, 1))


def test_beam_retains_component_with_delayed_value() -> None:
    catalog = catalog_fixture()
    model = model_fixture(catalog)
    query = Query(1, model.patch, 1600, 1, 1600, 1600)
    greedy = search(catalog, model, query, SearchConfig("greedy", 1, 2))
    beam = search(catalog, model, query, SearchConfig("beam", 3, 2))
    assert greedy.paths[0].path == (0, 1)
    assert beam.paths[0].path == (1, 2)
    assert beam.paths[0].score > greedy.paths[0].score
    validate_path(catalog, query, beam.paths[0])


def test_width_one_beam_equals_greedy() -> None:
    catalog = catalog_fixture()
    model = model_fixture(catalog)
    query = Query(1, model.patch, 800, 1, 800, 2400)
    first = search(catalog, model, query, SearchConfig("greedy", 99, 3))
    second = search(catalog, model, query, SearchConfig("beam", 1, 3))
    assert first.paths == second.paths
    assert first.expansions == second.expansions


def test_large_beam_matches_exhaustive_search() -> None:
    catalog = catalog_fixture()
    model = model_fixture(catalog)
    query = Query(1, model.patch, 800, 1, 800, 2400)
    frontier = [SearchState.initial(query)]
    terminal = []
    for _ in range(3):
        successors = []
        for state in frontier:
            children = [
                candidate
                for item in range(3)
                if (candidate := transition(catalog, model, query, state, item))
                is not None
            ]
            successors.extend(children)
            if not children:
                terminal.append(state)
        frontier = successors
    exact = select_final(terminal + frontier, 3)
    result = search(catalog, model, query, SearchConfig("beam", 100, 3))
    assert result.paths == exact


def test_purchase_preserves_net_worth_until_income_is_required() -> None:
    catalog = catalog_fixture()
    model = model_fixture(catalog)
    query = Query(1, model.patch, 6000, 1, 1200, 2400)
    first = transition(catalog, model, query, SearchState.initial(query), 1)
    assert first is not None
    assert (first.cash, first.net_worth, first.spent) == (400, 6000, 800)
    upgraded = transition(catalog, model, query, first, 2)
    assert upgraded is not None
    assert (upgraded.cash, upgraded.net_worth, upgraded.spent) == (0, 6400, 1600)
    assert upgraded.owned == 1 << 2
    validate_path(catalog, query, upgraded)


def test_repeated_purchase_and_budget_excess_are_rejected() -> None:
    catalog = catalog_fixture()
    model = model_fixture(catalog)
    query = Query(1, model.patch, 800, 1, 800, 800)
    state = SearchState.initial(query)
    assert transition(catalog, model, query, state, 2) is None
    purchased = transition(catalog, model, query, state, 0)
    assert purchased is not None
    assert transition(catalog, model, query, purchased, 0) is None
    assert transition(catalog, model, query, purchased, 1) is None


def test_unsupported_state_abstains() -> None:
    catalog = catalog_fixture()
    model = model_fixture(catalog, config=ScoringConfig(minimum_support=1001))
    query = Query(1, model.patch, 800, 1, 800, 2400)
    assert not search(catalog, model, query, SearchConfig()).paths


def test_patch_mismatch_is_rejected() -> None:
    catalog = catalog_fixture()
    model = model_fixture(catalog)
    query = Query(1, "another-patch", 800, 1, 800, 2400)
    with pytest.raises(ValueError, match="patch and catalog"):
        search(catalog, model, query, SearchConfig())


def test_validation_counts_cannot_train_the_model() -> None:
    with pytest.raises(ValueError, match="training statistics only"):
        ItemModel({"partition": "validation"}, ScoringConfig())


def test_bayesian_mean_shrinks_toward_state_baseline() -> None:
    catalog = catalog_fixture()
    weak = model_fixture(catalog, config=ScoringConfig(prior_strength=1))
    strong = model_fixture(catalog, config=ScoringConfig(prior_strength=1000))
    assert 0.5 < strong.cell(1, 800, 1, 0)[2] < weak.cell(1, 800, 1, 0)[2] < 0.65


def test_state_deduplication_retains_best_score() -> None:
    first = SearchState(3, 3, 0, 1600, 1600, 0.2, (0, 1), 100)
    second = SearchState(3, 3, 0, 1600, 1600, 0.3, (1, 0), 100)
    result, duplicates = distinct_states([first, second])
    assert result == [second]
    assert duplicates == 1


def test_diversity_measures_inventory_instead_of_item_order() -> None:
    assert inventory_distance(3, 3) == 0
    assert inventory_distance(3, 12) == 1
    candidates = [
        SearchState(3, 3, 0, 1600, 1600, 0.3, (0, 1), 100),
        SearchState(7, 7, 0, 2400, 2400, 0.299, (0, 1, 2), 100),
        SearchState(24, 24, 0, 1600, 1600, 0.298, (3, 4), 100),
    ]
    assert retain_diverse(candidates, 2, 0, 0) == candidates[:2]
    assert retain_diverse(candidates, 2, 0.02, 0) == [candidates[0], candidates[2]]


@pytest.mark.parametrize(
    "field", ["cash", "net_worth", "budget", "owned", "flex_slots"]
)
def test_negative_query_values_are_rejected(field: str) -> None:
    query = Query(1, "test", 800, 1, 800, 2400)
    with pytest.raises(ValueError, match="non-negative"):
        replace(query, **{field: -1})


def test_alternatives_exclude_prefixes_and_subset_cores() -> None:
    best = SearchState(7, 7, 0, 2400, 2400, 0.3, (0, 1, 2), 100)
    prefix = SearchState(3, 3, 0, 1600, 1600, 0.29, (0, 1), 100)
    extension = SearchState(15, 15, 0, 3200, 3200, 0.28, (3, 1, 0, 2), 100)
    alternative = SearchState(11, 11, 0, 2400, 2400, 0.27, (0, 1, 3), 100)
    assert select_final([prefix, extension, best, alternative], 3) == (
        best,
        alternative,
    )


def test_inventory_and_active_limits_apply_before_ranking() -> None:
    nodes = {
        item: ItemNode(
            item,
            f"item_{item}",
            f"Item {item}",
            800,
            "weapon",
            1,
            (),
            active=item <= 5,
            unique=True,
            max_count=1,
        )
        for item in range(1, 12)
    }
    catalog = Catalog.from_graph(ItemGraph(nodes))
    model = model_fixture(catalog, (0.6,) * 11)
    owned = sum(1 << item for item in (0, 1, 2, 3, 5, 6, 7, 8, 9))
    query = Query(1, model.patch, 8000, 1, 800, 800, owned)
    state = SearchState.initial(query)
    assert transition(catalog, model, query, state, 4) is None
    assert transition(catalog, model, query, state, 10) is None
    expanded = replace(query, flex_slots=1)
    result = transition(catalog, model, expanded, state, 10)
    assert result is not None
    validate_path(catalog, expanded, result)


def test_impossible_flex_capacity_is_rejected() -> None:
    with pytest.raises(ValueError, match="game limit"):
        Query(1, "test", 800, 1, 800, 800, flex_slots=4)


def test_candidate_filter_retains_items_supported_after_new_income() -> None:
    catalog = catalog_fixture()
    model = model_fixture(catalog)
    model.counts[:] = 0
    model.counts[0, 1, 1, 2] = 100
    query = Query(1, model.patch, 3800, 1, 0, 1600)
    initial = SearchState.initial(query)
    assert model.candidate_items(query, initial) == (2,)
    result = search(catalog, model, query, SearchConfig("beam", 4, 1))
    assert result.paths[0].path == (2,)
    assert result.paths[0].net_worth == 5400


def test_candidate_filter_does_not_use_unreachable_wealth_states() -> None:
    catalog = catalog_fixture()
    model = model_fixture(catalog)
    model.counts[:] = 0
    model.counts[0, 2, 1, 2] = 100
    query = Query(1, model.patch, 3800, 1, 0, 1600)
    assert model.candidate_items(query, SearchState.initial(query)) == ()
