"""Group all eligible routes, keeping upgrade components out of PICK ONE lists."""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from .purchase_guidance_types import PurchaseDecision

if TYPE_CHECKING:
    from .mechanics import ItemGraph
    from .purchase_guidance_types import PurchaseChoice


def _take_fork(
    seed: PurchaseChoice, remaining: list[PurchaseChoice]
) -> tuple[list[PurchaseChoice], list[PurchaseChoice]]:
    group = [seed]
    parts = set(seed.route[:-1])
    while True:
        joined = [row for row in remaining if parts.intersection(row.route[:-1])]
        if not joined:
            return group, remaining
        group.extend(joined)
        joined_ids = {row.item_id for row in joined}
        remaining = [row for row in remaining if row.item_id not in joined_ids]
        parts.update(item for row in joined for item in row.route[:-1])


def _forks(options: list[PurchaseChoice]) -> list[list[PurchaseChoice]]:
    groups: list[list[PurchaseChoice]] = []
    remaining = list(options)
    while remaining:
        group, remaining = _take_fork(remaining[0], remaining[1:])
        groups.append(group)
    return groups


def _decision(
    position: int, label: str, rows: list[PurchaseChoice], *, fork: bool = False
) -> PurchaseDecision:
    options = tuple(
        row.item_id
        for row in sorted(
            rows,
            key=lambda row: (-(row.timing.buyers if row.timing else 0), row.item_id),
        )
    )
    kind = (
        "PICK ONE"
        if len(rows) > 1
        else "UPGRADE"
        if len(rows[0].route) > 1
        else "OPTIONAL"
    )
    return PurchaseDecision(position, kind, label, options, fork)


def decisions_at(
    position: int, choices: tuple[PurchaseChoice, ...], graph: ItemGraph
) -> tuple[PurchaseDecision, ...]:
    cards = [
        card
        for card in choices
        if card.after_step == position and card.plan is not None
    ]
    ancestors = {item for card in cards for item in card.route[:-1]}
    options = [card for card in cards if card.item_id not in ancestors]
    grouped: dict[str, list[PurchaseChoice]] = defaultdict(list)
    result: list[PurchaseDecision] = []
    for group in _forks(options):
        if len(group) > 1:
            common = set.intersection(*(set(row.route[:-1]) for row in group))
            label = (
                "Upgrade "
                + ", ".join(graph.require(item).name for item in sorted(common))
                if common
                else "Shared component upgrades"
            )
            result.append(_decision(position, label, group, fork=True))
        else:
            card = group[0]
            label = (
                card.purpose.label
                if card.purpose.basis != "unclassified"
                else card.name
            )
            grouped[label].append(card)
    result.extend(_decision(position, label, rows) for label, rows in grouped.items())
    return tuple(sorted(result, key=lambda row: (row.purpose, row.options)))
