"""Count optional purchase positions within each build cohort without using outcomes."""

from __future__ import annotations


def _count_purchase_intervals(
    item_ids: list[int],
    path: tuple[int, ...],
    histories: dict[tuple[int, int], dict[int, float]],
) -> list[dict[str, object]]:
    return [_count_item_purchase_intervals(item, path, histories) for item in item_ids]


def _count_item_purchase_intervals(
    item: int, path: tuple[int, ...], histories: dict[tuple[int, int], dict[int, float]]
) -> dict[str, object]:
    counts = [0] * (len(path) + 1)
    buyers = 0
    for history in histories.values():
        bought = history.get(item)
        if bought is None:
            continue
        buyers += 1
        for position in range(len(counts)):
            left = history.get(path[position - 1]) if position else -1.0
            right = (
                history.get(path[position]) if position < len(path) else float("inf")
            )
            if left is not None and right is not None and left < bought < right:
                counts[position] += 1
    return {"item_id": item, "buyers": buyers, "counts_by_checkpoint": counts}
