"""Independent bounded Eclat and singleton-step PrefixSpan implementations."""

from __future__ import annotations

from collections import defaultdict

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


def sequences(times: np.ndarray) -> list[tuple[tuple[int, ...], ...]]:
    result = []
    for row in times:
        present = np.flatnonzero(row >= 0)
        batches = tuple(
            tuple(present[row[present] == time].tolist())
            for time in sorted(set(row[present]))
        )
        result.append(batches)
    return result


def project(
    database: list[tuple[tuple[int, ...], ...]],
    projected: list[tuple[int, int]],
    prefix: tuple[int, ...],
) -> dict[int, list[tuple[int, int]]]:
    extensions = defaultdict(list)
    for identity, start in projected:
        seen = set(prefix)
        for offset in range(start, len(database[identity])):
            for item in database[identity][offset]:
                if item not in seen:
                    extensions[item].append((identity, offset + 1))
                    seen.add(item)
    return dict(extensions)


def extend_sequence(
    database: list[tuple[tuple[int, ...], ...]],
    projected: list[tuple[int, int]],
    prefix: tuple[int, ...],
    minimum: int,
    length: int,
    result: PatternCounts,
) -> None:
    for item, following in sorted(project(database, projected, prefix).items()):
        if len(following) < minimum:
            continue
        pattern = (*prefix, item)
        if len(pattern) == length:
            result[pattern] = len(following)
        else:
            extend_sequence(database, following, pattern, minimum, length, result)


def prefixspan(
    times: np.ndarray, minimum: int = 100, length: int = 3
) -> dict[tuple[int, ...], int]:
    database = sequences(times)
    result = {}
    extend_sequence(
        database,
        [(index, 0) for index in range(len(database))],
        (),
        minimum,
        length,
        result,
    )
    return result
