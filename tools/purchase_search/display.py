"""Factor complete build variants without changing their item combinations."""

from __future__ import annotations

from dataclasses import dataclass
from functools import reduce
from operator import and_


@dataclass(frozen=True)
class BuildVariant:
    name: str
    core: frozenset[str]
    purchase_order: tuple[str, ...]


@dataclass(frozen=True)
class FactoredVariants:
    shared_core: frozenset[str]
    additions: tuple[frozenset[str], ...]
    common_purchase_prefix: tuple[str, ...]
    repeated_cards: int
    factored_cards: int


def factor_variants(variants: tuple[BuildVariant, ...]) -> FactoredVariants:
    if not variants:
        raise ValueError("At least one complete variant is required")
    if any(not variant.core for variant in variants):
        raise ValueError("Every variant requires a non-empty core")
    shared = reduce(and_, (variant.core for variant in variants))
    additions = tuple(variant.core - shared for variant in variants)
    prefix = []
    shortest = min(len(variant.purchase_order) for variant in variants)
    for position in range(shortest):
        values = {variant.purchase_order[position] for variant in variants}
        if len(values) != 1:
            break
        prefix.append(next(iter(values)))
    return FactoredVariants(
        shared,
        additions,
        tuple(prefix),
        sum(len(variant.core) for variant in variants),
        len(shared) + sum(len(items) for items in additions),
    )


def recover_cores(factored: FactoredVariants) -> tuple[frozenset[str], ...]:
    return tuple(factored.shared_core | addition for addition in factored.additions)


def card_rows(card_counts: tuple[int, ...], columns: int) -> int:
    if columns < 1 or any(count < 0 for count in card_counts):
        raise ValueError("Card counts and column capacity are invalid")
    return sum((count + columns - 1) // columns for count in card_counts)


def layout_dimensions(bands: tuple[tuple[int, ...], ...]) -> tuple[int, int]:
    widths = [
        sum(max(128, 12 + 84 * count) for count in band) + 12 * (len(band) - 1)
        for band in bands
    ]
    return max(widths), 164 * len(bands) + 12 * (len(bands) - 1)
