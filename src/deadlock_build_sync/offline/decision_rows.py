"""Index checkpoint observations without changing their original order."""

from __future__ import annotations

from collections.abc import Iterator
from heapq import merge


class IndexedDecisionRows:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = tuple(rows)
        self._positions: dict[object, list[int]] = {}
        for index, row in enumerate(rows):
            self._positions.setdefault(row["item_id"], []).append(index)

    def select_items(self, item: int, comparator: int) -> Iterator[dict[str, object]]:
        positions = merge(
            *(self._positions.get(action, []) for action in {item, comparator})
        )
        return (self._rows[index] for index in positions)


type DecisionRows = list[dict[str, object]] | IndexedDecisionRows
