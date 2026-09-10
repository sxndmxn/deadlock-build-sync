"""Define the shared experiment records and item catalog."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from deadlock_build_sync.mechanics_assets import MAX_FLEX_SLOTS

if TYPE_CHECKING:
    from deadlock_build_sync.mechanics import ItemGraph

GUIDE_CHECKPOINTS = ((4800, 600), (12800, 1201), (25600, 1801))


def mask_indices(mask: int) -> tuple[int, ...]:
    """Return the set bit indices in increasing order.

    Returns:
        The indices of the set bits.

    """
    result = []
    while mask:
        bit = mask & -mask
        result.append(bit.bit_length() - 1)
        mask ^= bit
    return tuple(result)


@dataclass(frozen=True)
class Catalog:
    graph: ItemGraph
    item_ids: tuple[int, ...]
    names: tuple[str, ...]
    costs: tuple[int, ...]
    components: tuple[int, ...]
    ancestors: tuple[int, ...]
    active_mask: int

    @classmethod
    def from_graph(cls, graph: ItemGraph) -> Catalog:
        item_ids = tuple(sorted(graph.nodes))
        index = {item: position for position, item in enumerate(item_ids)}
        return cls(
            graph,
            item_ids,
            tuple(graph.require(item).name for item in item_ids),
            tuple(graph.require(item).cost for item in item_ids),
            tuple(
                sum(1 << index[component] for component in graph.components[item])
                for item in item_ids
            ),
            tuple(
                sum(
                    1 << index[component]
                    for component in graph.transitive_components(item)
                )
                for item in item_ids
            ),
            sum(1 << index[item] for item in item_ids if graph.require(item).active),
        )

    def mask(self, item_ids: tuple[int, ...]) -> int:
        index = {item: position for position, item in enumerate(self.item_ids)}
        return sum(1 << index[item] for item in set(item_ids) if item in index)

    def item_names(self, mask: int) -> tuple[str, ...]:
        return tuple(self.names[index] for index in mask_indices(mask))


@dataclass(frozen=True)
class Query:
    hero: int
    patch: str
    net_worth: int
    relative_state: int
    cash: int
    budget: int
    owned: int = 0
    flex_slots: int = 0

    def __post_init__(self) -> None:
        """Reject invalid query values.

        Raises:
            ValueError: A query value violates a state constraint.

        """
        if min(self.net_worth, self.cash, self.budget, self.owned, self.flex_slots) < 0:
            raise ValueError("Query values must be non-negative")
        if self.relative_state not in {0, 1, 2}:
            raise ValueError("Relative wealth state must be 0, 1, or 2")
        if self.cash > self.net_worth:
            raise ValueError("Cash cannot exceed net worth")
        if self.flex_slots > MAX_FLEX_SLOTS:
            raise ValueError("Flex capacity exceeds the game limit")


@dataclass(frozen=True)
class ScoringConfig:
    prior_strength: float = 100.0
    uncertainty_multiplier: float = 0.5
    cost_exponent: float = 0.5
    discount: float = 0.97
    minimum_support: int = 30
    state_aware: bool = True

    def __post_init__(self) -> None:
        """Reject invalid scoring parameters.

        Raises:
            ValueError: A scoring parameter is outside its permitted range.

        """
        if self.prior_strength <= 0 or self.minimum_support < 1:
            raise ValueError("Prior strength and minimum support must be positive")
        if self.uncertainty_multiplier < 0 or not 0 < self.discount <= 1:
            raise ValueError("Uncertainty or discount is invalid")
        if not 0 <= self.cost_exponent <= 1:
            raise ValueError("Cost exponent must be between zero and one")


@dataclass(frozen=True)
class CombinationConfig:
    minimum_owners: int = 100
    minimum_items: int = 3

    def __post_init__(self) -> None:
        """Reject non-positive support limits.

        Raises:
            ValueError: A support limit is not positive.

        """
        if self.minimum_owners < 1 or self.minimum_items < 1:
            raise ValueError("Combination support limits must be positive")


@dataclass(frozen=True)
class SearchConfig:
    method: str = "greedy"
    width: int = 1
    depth: int = 8
    alternatives: int = 3
    diversity: float = 0.02

    def __post_init__(self) -> None:
        """Reject invalid search parameters.

        Raises:
            ValueError: A method or search limit is invalid.

        """
        if self.method not in {"greedy", "beam", "diverse", "eclat", "leiden"}:
            raise ValueError("Unknown search method")
        if min(self.width, self.depth, self.alternatives) < 1 or self.diversity < 0:
            raise ValueError("Search limits must be positive")


@dataclass(frozen=True)
class SearchState:
    owned: int
    purchased: int
    cash: int
    net_worth: int
    spent: int
    score: float
    path: tuple[int, ...]
    minimum_support: int

    @classmethod
    def initial(cls, query: Query) -> SearchState:
        return cls(query.owned, query.owned, query.cash, query.net_worth, 0, 0.0, (), 0)

    def identity(self) -> tuple[int, int, int, int, int]:
        return self.owned, self.purchased, self.cash, self.net_worth, self.spent


@dataclass(frozen=True)
class SearchResult:
    paths: tuple[SearchState, ...]
    expansions: int
    duplicate_states: int
    elapsed_seconds: float
