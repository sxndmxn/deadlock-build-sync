"""Search valid purchase sequences with one common transition and score."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from deadlock_build_sync.mechanics import InventoryState, purchase_item
from deadlock_build_sync.mechanics_assets import BASE_INVENTORY_SLOTS, MAX_ACTIVE_ITEMS

from .records import (
    Catalog,
    Query,
    SearchConfig,
    SearchResult,
    SearchState,
    mask_indices,
)

if TYPE_CHECKING:
    from .evidence import JointSupport
    from .model import ItemModel


@dataclass(frozen=True)
class SearchGuidance:
    themes: tuple[int, ...] = ()
    support: JointSupport | None = None


def path_order(state: SearchState) -> tuple[float, tuple[int, ...]]:
    return -state.score, state.path


def inventory_distance(first: int, second: int) -> float:
    union = (first | second).bit_count()
    return 1 - (first & second).bit_count() / union if union else 0.0


def transition(
    catalog: Catalog, model: ItemModel, query: Query, state: SearchState, item: int
) -> SearchState | None:
    bit = 1 << item
    if state.purchased & bit:
        return None
    consumed = state.owned & catalog.components[item]
    cash_cost = catalog.costs[item] - sum(
        catalog.costs[part] for part in mask_indices(consumed)
    )
    if cash_cost <= 0 or state.spent + cash_cost > query.budget:
        return None
    owned = (state.owned & ~consumed) | bit
    if owned.bit_count() > BASE_INVENTORY_SLOTS + query.flex_slots:
        return None
    if (owned & catalog.active_mask).bit_count() > MAX_ACTIVE_ITEMS:
        return None
    income = max(0, cash_cost - state.cash)
    net_worth = state.net_worth + income
    utility, support = model.action_utility(
        query, net_worth, item, cash_cost, len(state.path)
    )
    if support < model.config.minimum_support:
        return None
    return SearchState(
        owned,
        state.purchased | bit,
        max(0, state.cash - cash_cost),
        net_worth,
        state.spent + cash_cost,
        state.score + utility,
        (*state.path, item),
        min(state.minimum_support, support) if state.path else support,
    )


def distinct_states(states: list[SearchState]) -> tuple[list[SearchState], int]:
    best = {}
    for state in states:
        identity = state.identity()
        previous = best.get(identity)
        if previous is None or path_order(state) < path_order(previous):
            best[identity] = state
    return sorted(best.values(), key=path_order), len(states) - len(best)


def retain_diverse(
    candidates: list[SearchState], width: int, diversity: float, initial: int
) -> list[SearchState]:
    if diversity == 0:
        return candidates[:width]
    selected = [candidates[0]]
    remaining = candidates[1:]
    penalties = {state.path: 0.0 for state in remaining}
    while remaining and len(selected) < width:
        previous = selected[-1].owned & ~initial
        for state in remaining:
            similarity = 1 - inventory_distance(previous, state.owned & ~initial)
            penalties[state.path] = max(penalties[state.path], similarity)
        chosen = min(
            remaining,
            key=lambda state: (
                -(state.score - diversity * penalties[state.path]),
                state.path,
            ),
        )
        selected.append(chosen)
        remaining.remove(chosen)
    return selected


def retain_structured(
    candidates: list[SearchState], width: int, themes: tuple[int, ...], initial: int
) -> list[SearchState]:
    if not themes:
        return candidates[:width]
    selected = candidates[: max(1, width // 2)]
    remaining = candidates[len(selected) :]
    for theme in themes:
        if not remaining or len(selected) >= width:
            break
        chosen = min(
            remaining,
            key=lambda state: (
                inventory_distance(state.owned & ~initial, theme & ~initial),
                *path_order(state),
            ),
        )
        if not (chosen.owned & theme & ~initial):
            continue
        selected.append(chosen)
        remaining.remove(chosen)
    selected.extend(remaining[: max(0, width - len(selected))])
    return selected


def select_final(states: list[SearchState], count: int) -> tuple[SearchState, ...]:
    inventories = set()
    selected = []
    for state in sorted(states, key=path_order):
        if not state.path or state.owned in inventories:
            continue
        if any(
            state.path[: len(previous.path)] == previous.path
            or previous.path[: len(state.path)] == state.path
            or state.owned & previous.owned in {state.owned, previous.owned}
            for previous in selected
        ):
            continue
        selected.append(state)
        inventories.add(state.owned)
        if len(selected) == count:
            break
    return tuple(selected)


def expand_frontier(
    frontier: list[SearchState],
    catalog: Catalog,
    model: ItemModel,
    query: Query,
    support: JointSupport | None,
) -> tuple[list[SearchState], list[SearchState], int]:
    successors = []
    terminal = []
    expansions = 0
    for state in frontier:
        if support is not None and support.complete(state.owned):
            terminal.append(state)
        children = []
        candidates = model.candidate_items(query, state)
        expansions += len(candidates)
        for item in candidates:
            candidate = transition(catalog, model, query, state, item)
            if candidate is not None and (
                support is None or support.feasible(candidate.owned)
            ):
                children.append(candidate)
        if children:
            successors.extend(children)
        elif support is None:
            terminal.append(state)
    return successors, terminal, expansions


def search(
    catalog: Catalog,
    model: ItemModel,
    query: Query,
    config: SearchConfig,
    guidance: SearchGuidance | None = None,
) -> SearchResult:
    started = time.perf_counter()
    if query.patch != model.patch or catalog.item_ids != model.item_ids:
        raise ValueError("Search query does not match the model patch and catalog")
    if query.hero not in model.hero_index:
        raise ValueError("The hero has no training model")
    if query.owned >> len(catalog.item_ids):
        raise ValueError("The initial inventory contains unknown items")
    width = 1 if config.method == "greedy" else config.width
    guidance = guidance or SearchGuidance()
    support = guidance.support
    initial = SearchState.initial(query)
    if (
        initial.owned.bit_count() > BASE_INVENTORY_SLOTS + query.flex_slots
        or (initial.owned & catalog.active_mask).bit_count() > MAX_ACTIVE_ITEMS
    ):
        return SearchResult((), 0, 0, time.perf_counter() - started)
    frontier = [initial]
    terminal = []
    expansions = 0
    duplicates = 0
    for _ in range(config.depth):
        successors, completed, attempts = expand_frontier(
            frontier, catalog, model, query, support
        )
        expansions += attempts
        terminal.extend(completed)
        if not successors:
            frontier = []
            break
        candidates, duplicate_count = distinct_states(successors)
        duplicates += duplicate_count
        if config.method == "diverse":
            frontier = retain_diverse(candidates, width, config.diversity, query.owned)
        elif config.method in {"eclat", "leiden"}:
            frontier = retain_structured(
                candidates, width, guidance.themes, query.owned
            )
        else:
            frontier = candidates[:width]
    terminal.extend(
        state for state in frontier if support is None or support.complete(state.owned)
    )
    return SearchResult(
        select_final(terminal, config.alternatives),
        expansions,
        duplicates,
        time.perf_counter() - started,
    )


def validate_path(catalog: Catalog, query: Query, result: SearchState) -> None:
    """Replay the result with the independent production mechanics functions.

    Raises:
        ValueError: The path violates purchase rules or has an incorrect final state.

    """
    inventory = InventoryState(
        tuple(catalog.item_ids[index] for index in mask_indices(query.owned)),
        query.flex_slots,
    )
    cash = query.cash
    wealth = query.net_worth
    spent = 0
    purchased = set(inventory.owned)
    for index in result.path:
        item = catalog.item_ids[index]
        if item in purchased:
            raise ValueError("The guide repeats a purchase action")
        price = catalog.graph.incremental_cash_cost(item, inventory.owned)
        spent += price
        if spent > query.budget or price <= 0:
            raise ValueError("The guide exceeds its purchase budget")
        wealth += max(0, price - cash)
        cash = max(0, cash - price)
        inventory = purchase_item(catalog.graph, inventory, item)
        purchased.add(item)
    expected = catalog.mask(inventory.owned), cash, wealth, spent
    actual = result.owned, result.cash, result.net_worth, result.spent
    if expected != actual:
        raise ValueError("Search state differs from independent purchase replay")
