"""Build explicit decisions without confusing components with alternatives."""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from deadlock_build_sync.mechanics import ItemGraph


def route_for(item: int, graph: ItemGraph) -> list[int]:
    route: list[int] = []
    for component in graph.components[item]:
        route.extend(
            value for value in route_for(component, graph) if value not in route
        )
    return [*route, item]


def option_for(item: int, cards: dict, graph: ItemGraph) -> dict:
    route = route_for(item, graph)
    return {
        "item_id": item,
        "kind": "upgrade" if len(route) > 1 else "optional",
        "route": route,
        "choice_items": [value for value in route if value in cards],
        "stages": [
            {"item_id": value, "extra_path_cost": cards[value]["extra_path_cost"]}
            for value in route
            if value in cards
        ],
        "purpose": cards[item]["purpose"],
    }


def take_fork(seed: dict, remaining: list[dict]) -> tuple[list[dict], list[dict]]:
    group = [seed]
    parts = set(seed["route"][:-1])
    while True:
        joined = [row for row in remaining if parts & set(row["route"][:-1])]
        if not joined:
            return group, remaining
        group.extend(joined)
        ids = {row["item_id"] for row in joined}
        remaining = [row for row in remaining if row["item_id"] not in ids]
        parts.update(item for row in joined for item in row["route"][:-1])


def fork_groups(options: list[dict]) -> list[list[dict]]:
    """Join sibling routes by shared components.

    Returns:
        Connected groups, including components outside the pool.

    """
    groups, remaining = [], list(options)
    while remaining:
        group, remaining = take_fork(remaining[0], remaining[1:])
        groups.append(group)
    return groups


def rank_option(option: dict, cards: dict) -> tuple:
    evidence = cards[option["item_id"]]["purchase_evidence"]
    return (
        -evidence["buyers"],
        evidence["time_seconds_q25_q50_q75"][1],
        option["item_id"],
    )


def decisions_for(cards: list[dict], graph: ItemGraph) -> list[dict]:
    by_id = {card["item_id"]: card for card in cards}
    ancestors = {
        item for card in cards for item in graph.transitive_components(card["item_id"])
    }
    options = [
        option_for(item, by_id, graph)
        for item in sorted(by_id)
        if item not in ancestors
    ]
    result = group_options(options, graph)
    for decision in result:
        rows = decision["options"]
        rows.sort(key=lambda option: rank_option(option, by_id))
        decision["kind"] = "pick_one" if len(rows) > 1 else rows[0]["kind"]
        decision["instruction"] = (
            "Choose the next purchase for this need, or follow the core"
        )
    return sorted(
        result, key=lambda row: (row["purpose"], row["options"][0]["item_id"])
    )


def group_options(options: list[dict], graph: ItemGraph) -> list[dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    result = []
    for group in fork_groups(options):
        if len(group) > 1:
            common = set.intersection(*(set(row["route"][:-1]) for row in group))
            label = (
                "Upgrade "
                + ", ".join(graph.require(item).name for item in sorted(common))
                if common
                else "Shared component upgrades"
            )
            result.append({
                "purpose": label,
                "relationship": "upgrade_fork",
                "options": group,
            })
        else:
            option = group[0]
            label = option["purpose"]
            if label == "General utility":
                label = graph.require(option["item_id"]).name + " — general utility"
            grouped[label].append(option)
    result.extend(
        {
            "purpose": label,
            "relationship": "same_need" if len(rows) > 1 else "single_route",
            "options": rows,
        }
        for label, rows in grouped.items()
    )
    return result


def checkpoints_for(
    path: list[int], choices: list[dict], graph: ItemGraph
) -> list[dict]:
    checkpoints = []
    for index in range(len(path) + 1):
        cards = [
            card
            for card in choices
            if card["placement"]["after_step"] == index and card["branch"] is not None
        ]
        checkpoints.append({
            "after_step": index,
            "after_item": path[index - 1] if index else None,
            "before_item": path[index] if index < len(path) else None,
            "choices": [card["item_id"] for card in cards],
            "decisions": decisions_for(cards, graph),
        })
    return checkpoints


def upgrade_groups(pool: dict, graph: ItemGraph, core_path: list[int]) -> list[dict]:
    shown = set(core_path) | {item for items in pool.values() for item in items}
    for item in list(shown):
        shown.update(graph.transitive_components(item))
    groups = []
    for component in sorted(shown):
        parents = [parent for parent in graph.children[component] if parent in shown]
        if parents:
            groups.append({
                "component": component,
                "parents": parents,
                "kind": "pick one upgrade" if len(parents) > 1 else "upgrade chain",
                "shared_component_cost": graph.require(component).cost,
                "note": f"Both routes need another {graph.require(component).name} ({graph.require(component).cost:,} souls)"
                if len(parents) > 1
                else "The upgrade consumes the component and credits its cost",
            })
    return groups


def attach_decisions(guide: dict, graph: ItemGraph) -> None:
    path = [action["item_id"] for action in guide["default_path"]["actions"]]
    guide["checkpoints"] = checkpoints_for(path, guide["choices"], graph)
    guide["unplaced_choices"] = [
        card["item_id"]
        for card in guide["choices"]
        if card["placement"]["after_step"] is None
    ]
    guide["blocked_choices"] = [
        card["item_id"]
        for card in guide["choices"]
        if card["placement"]["after_step"] is not None and card["branch"] is None
    ]
    guide["upgrade_groups"] = upgrade_groups(guide["item_pool"], graph, path)
