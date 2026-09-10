from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from .mechanics_assets import (
    MechanicsError,
    _is_populated,
    normalize_mechanical_value,
)
from .value_validation import integer, object_dict, object_list


@dataclass(frozen=True)
class ItemNode:
    item_id: int
    class_name: str
    name: str
    cost: int
    slot: str
    tier: int
    component_classes: tuple[str, ...]
    active: bool
    unique: bool
    max_count: int


class ItemGraph:
    """Validated directed acyclic graph of current item upgrades."""

    def __init__(self, nodes: dict[int, ItemNode]) -> None:
        if not nodes:
            raise MechanicsError("item graph is empty")
        self.nodes = dict(nodes)
        self.by_class = {node.class_name: node for node in nodes.values()}
        if len(self.by_class) != len(nodes):
            raise MechanicsError("item class names must be unique")
        self.components: dict[int, tuple[int, ...]] = {}
        children: dict[int, list[int]] = {item_id: [] for item_id in nodes}
        for node in nodes.values():
            resolved: list[int] = []
            for class_name in node.component_classes:
                component = self.by_class.get(class_name)
                if component is None:
                    raise MechanicsError(
                        f"item {node.name} references missing component {class_name}"
                    )
                resolved.append(component.item_id)
                children[component.item_id].append(node.item_id)
            self.components[node.item_id] = tuple(resolved)
        self.children = {
            item_id: tuple(sorted(item_children))
            for item_id, item_children in children.items()
        }
        self._component_ancestors: dict[int, tuple[int, ...]] = {}
        self._validate_acyclic()

    @classmethod
    def from_assets(cls, assets: list[dict[str, object]]) -> ItemGraph:
        nodes: dict[int, ItemNode] = {}
        for asset in assets:
            item_id = asset.get("id")
            class_name = asset.get("class_name")
            if (
                not isinstance(item_id, int)
                or not isinstance(class_name, str)
                or not asset.get("shopable")
                or asset.get("disabled")
            ):
                continue
            raw_components = object_list(asset.get("component_items")) or []
            if not all(isinstance(component, str) for component in raw_components):
                raise MechanicsError(f"item {item_id} has malformed components")
            max_count = asset.get("max_count")
            nodes[item_id] = ItemNode(
                item_id=item_id,
                class_name=class_name,
                name=str(asset.get("name") or class_name),
                cost=max(0, integer(asset.get("cost"), default=0)),
                slot=str(asset.get("item_slot_type") or "unknown").casefold(),
                tier=integer(asset.get("item_tier"), default=0),
                component_classes=tuple(
                    component
                    for component in raw_components
                    if isinstance(component, str)
                ),
                active=bool(asset.get("is_active_item")),
                unique=bool(asset.get("is_unique", True)),
                max_count=(max(1, int(max_count)) if isinstance(max_count, int) else 1),
            )
        return cls(nodes)

    def _validate_acyclic(self) -> None:
        visiting: set[int] = set()
        visited: set[int] = set()

        def visit(item_id: int) -> None:
            if item_id in visiting:
                raise MechanicsError("item component graph contains a cycle")
            if item_id in visited:
                return
            visiting.add(item_id)
            for component_id in self.components[item_id]:
                visit(component_id)
            visiting.remove(item_id)
            visited.add(item_id)

        for item_id in self.nodes:
            visit(item_id)

    def transitive_components(self, item_id: int) -> tuple[int, ...]:
        """Return every component ancestor once in dependency order.

        Returns:
            Component item IDs, with nested components before their parents.

        """
        self.require(item_id)
        if item_id in self._component_ancestors:
            return self._component_ancestors[item_id]
        ordered: list[int] = []
        seen: set[int] = set()

        def collect(current: int) -> None:
            for component_id in self.components[current]:
                collect(component_id)
                if component_id not in seen:
                    seen.add(component_id)
                    ordered.append(component_id)

        collect(item_id)
        result = tuple(ordered)
        self._component_ancestors[item_id] = result
        return result

    def require(self, item_id: int) -> ItemNode:
        """Resolve one current item.

        Returns:
            The item node.

        Raises:
            MechanicsError: If the item does not exist in the snapshot.

        """
        try:
            return self.nodes[item_id]
        except KeyError as error:
            raise MechanicsError(f"unknown current item {item_id}") from error

    def credited_component_value(
        self,
        item_id: int,
        owned: tuple[int, ...],
    ) -> int:
        """Calculate consumed owned component catalog value.

        Returns:
            Value credited by direct owned components of the child.

        """
        owned_set = set(owned)
        return sum(
            self.nodes[component_id].cost
            for component_id in self.components[self.require(item_id).item_id]
            if component_id in owned_set
        )

    def incremental_cash_cost(self, item_id: int, owned: tuple[int, ...]) -> int:
        """Calculate current child price less credited owned components.

        Returns:
            Non-negative liquid currency required for the purchase.

        """
        node = self.require(item_id)
        return max(0, node.cost - self.credited_component_value(item_id, owned))

    def total_tree_investment(self, item_id: int) -> int:
        """Return the catalog investment represented by an upgrade tree.

        Returns:
            Root price, which includes the credited component value in current assets.

        """
        return self.require(item_id).cost


@dataclass(frozen=True)
class CategoryBonus:
    threshold: int
    values: dict[str, object]


@dataclass(frozen=True)
class CategoryBonusTable:
    categories: dict[str, tuple[CategoryBonus, ...]]

    @classmethod
    def from_asset(cls, asset: dict[str, object]) -> CategoryBonusTable:
        raw = asset.get("cost_bonuses")
        if not isinstance(raw, dict):
            raise MechanicsError("authoritative cost_bonuses are missing")
        categories: dict[str, tuple[CategoryBonus, ...]] = {}
        for category, rows in raw.items():
            categories[str(category).casefold()] = _parse_category_bonuses(
                category, rows
            )
        return cls(categories)

    def crossed(
        self,
        category: str,
        previous_spend: int,
        new_spend: int,
    ) -> tuple[CategoryBonus, ...]:
        """Return breakpoints crossed once by a monotone spend transition.

        Returns:
            Bonuses whose threshold lies after previous and at/before new spend.

        Raises:
            MechanicsError: If cumulative spend moves backwards.

        """
        if new_spend < previous_spend:
            raise MechanicsError("category spend cannot move backwards")
        return tuple(
            bonus
            for bonus in self.categories.get(category.casefold(), ())
            if previous_spend < bonus.threshold <= new_spend
        )


def _parse_category_bonus_rows(category: object, rows: object) -> list[object]:
    if isinstance(rows, dict):
        return [
            {"threshold": threshold, "value": value}
            for threshold, value in rows.items()
        ]
    if not isinstance(rows, list):
        raise MechanicsError(f"malformed {category} cost bonuses")
    return cast("list[object]", rows)


def _parse_category_bonus(category: object, row: object) -> CategoryBonus:
    document = object_dict(row)
    if document is None:
        raise MechanicsError(f"malformed {category} cost bonus")
    threshold = document.get(
        "gold_threshold",
        document.get("threshold", document.get("cost")),
    )
    if isinstance(threshold, str) and threshold.isdigit():
        threshold = int(threshold)
    if not isinstance(threshold, int) or threshold < 0:
        raise MechanicsError(f"invalid {category} bonus threshold")
    values = {
        key: normalize_mechanical_value(value)
        for key, value in sorted(document.items())
        if key not in {"gold_threshold", "threshold", "cost"} and _is_populated(value)
    }
    return CategoryBonus(threshold, values)


def _parse_category_bonuses(
    category: object, rows: object
) -> tuple[CategoryBonus, ...]:
    ordered = sorted(
        (
            _parse_category_bonus(category, row)
            for row in _parse_category_bonus_rows(category, rows)
        ),
        key=lambda bonus: bonus.threshold,
    )
    if len({bonus.threshold for bonus in ordered}) != len(ordered):
        raise MechanicsError(f"duplicate {category} bonus threshold")
    return tuple(ordered)
