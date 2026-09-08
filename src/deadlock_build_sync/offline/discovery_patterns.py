"""Bounded Eclat mining for observed item sets."""

from __future__ import annotations

import numpy as np

from .discovery_types import PatternCounts


def eclat(
    matrix: np.ndarray, minimum: int = 100, length: int = 3
) -> dict[tuple[int, ...], int]:
    vertical = []
    for item in range(matrix.shape[1]):
        bits = int.from_bytes(
            np.packbits(matrix[:, item], bitorder="little").tobytes(), "little"
        )
        if bits.bit_count() >= minimum:
            vertical.append((item, bits))
    result = {}
    extend_itemset((), vertical, minimum, length, result)
    return result


def extend_itemset(
    prefix: tuple[int, ...],
    vertical: list[tuple[int, int]],
    minimum: int,
    length: int,
    result: PatternCounts,
) -> None:
    for offset, (item, tids) in enumerate(vertical):
        following = (*prefix, item)
        if len(following) == length:
            result[following] = tids.bit_count()
            continue
        suffix = [
            (other, tids & remaining)
            for other, remaining in vertical[offset + 1 :]
            if (tids & remaining).bit_count() >= minimum
        ]
        extend_itemset(following, suffix, minimum, length, result)
