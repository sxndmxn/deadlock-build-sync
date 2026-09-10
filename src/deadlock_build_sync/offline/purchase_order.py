"""Shared pairwise agreement ordering for production and comparisons."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections import Counter


def _ranked_agreement_orders(
    item_ids: tuple[int, ...],
    precedence: Counter[tuple[int, int]],
) -> list[tuple[int, tuple[int, ...]]]:
    ordered_items = tuple(sorted(item_ids))
    states: dict[int, dict[tuple[int, ...], int]] = {0: {(): 0}}
    full_mask = (1 << len(ordered_items)) - 1
    for mask in range(full_mask + 1):
        current = states.get(mask)
        if current is None:
            continue
        for index, item_id in enumerate(ordered_items):
            bit = 1 << index
            if mask & bit:
                continue
            added = sum(
                precedence[prior_id, item_id]
                for prior_index, prior_id in enumerate(ordered_items)
                if mask & (1 << prior_index)
            )
            target_mask = mask | bit
            target = states.setdefault(target_mask, {})
            for path, score in current.items():
                next_path = (*path, item_id)
                target[next_path] = score + added
    return sorted(
        ((score, path) for path, score in states[full_mask].items()),
        key=lambda value: (-value[0], value[1]),
    )
