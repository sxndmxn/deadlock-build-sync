from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

from .snapshot import sha256_json

BASE_INVENTORY_SLOTS = 9
MAX_FLEX_SLOTS = 3
MAX_ACTIVE_ITEMS = 4
DEFAULT_ABILITY_UPGRADE_COSTS = (1, 2, 5)

_TAG_PATTERN = re.compile(r"<[^>]+>")
_TOKEN_PATTERN = re.compile(r"\{[a-zA-Z0-9_.:-]+\}")
_SPACE_PATTERN = re.compile(r"\s+")


class MechanicsError(ValueError):
    """Raised when pinned mechanics are missing, contradictory, or illegal."""


def _is_populated(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, (str, list, tuple, dict)):
        return bool(value)
    return True


def clean_mechanical_text(value: object) -> str:
    """Normalize localized mechanics text while retaining its meaning.

    Returns:
        Plain single-line text with markup and unresolved template tokens removed.

    """
    if not isinstance(value, str):
        return ""
    unescaped = html.unescape(value)
    without_markup = _TAG_PATTERN.sub(" ", unescaped)
    without_tokens = _TOKEN_PATTERN.sub(" ", without_markup)
    return _SPACE_PATTERN.sub(" ", without_tokens).strip()


def normalize_mechanical_value(value: Any) -> Any:
    """Recursively normalize a mechanics payload without dropping populated fields.

    Returns:
        A JSON-compatible value with deterministic text and key ordering.

    """
    if isinstance(value, dict):
        return {
            str(key): normalize_mechanical_value(nested)
            for key, nested in sorted(value.items(), key=lambda pair: str(pair[0]))
            if _is_populated(nested)
        }
    if isinstance(value, list):
        return [normalize_mechanical_value(nested) for nested in value]
    if isinstance(value, tuple):
        return [normalize_mechanical_value(nested) for nested in value]
    if isinstance(value, str):
        cleaned = clean_mechanical_text(value)
        return cleaned or value.strip()
    return value


def normalize_hero_description(value: object) -> dict[str, str]:
    """Preserve each non-empty lore, role, playstyle, or description field.

    Returns:
        A keyed description rather than a lossy concatenated string.

    """
    if isinstance(value, str):
        cleaned = clean_mechanical_text(value)
        return {"summary": cleaned} if cleaned else {}
    if not isinstance(value, dict):
        return {}
    result: dict[str, str] = {}
    for key, nested in sorted(value.items(), key=lambda pair: str(pair[0])):
        cleaned = clean_mechanical_text(nested)
        if cleaned:
            result[str(key)] = cleaned
    return result


MECHANICS_FIELDS = (
    "ability_type",
    "behaviour",
    "cast_range",
    "channel_time",
    "component_items",
    "cooldown",
    "cost",
    "cost_bonuses",
    "damage_type",
    "description",
    "duration",
    "imbue",
    "is_active_item",
    "is_unique",
    "item_slot_type",
    "item_tier",
    "level_info",
    "max_count",
    "properties",
    "radius",
    "scaling_stats",
    "targeting",
    "unlock_level",
    "upgrade_costs",
    "upgrades",
    "weapon_info",
)


def extract_asset_mechanics(asset: dict[str, Any]) -> dict[str, Any]:
    """Extract all claim-relevant structured mechanics from one asset.

    Returns:
        An identity-bearing normalized mechanics record.

    Raises:
        MechanicsError: If the asset has no stable numeric identity.

    """
    asset_id = asset.get("id")
    if not isinstance(asset_id, int):
        raise MechanicsError("mechanics asset is missing a numeric id")
    result: dict[str, Any] = {
        "id": asset_id,
        "class_name": str(asset.get("class_name") or ""),
        "name": clean_mechanical_text(asset.get("name")) or f"Asset {asset_id}",
        "type": str(asset.get("type") or "unknown"),
    }
    for field in MECHANICS_FIELDS:
        value = asset.get(field)
        if _is_populated(value):
            result[field] = normalize_mechanical_value(value)
    return result


def build_hero_mechanics(
    hero: dict[str, Any],
    assets: list[dict[str, Any]],
) -> dict[str, Any]:
    """Create a complete, fingerprinted kit record from pinned asset payloads.

    Returns:
        Hero description, level scaling, and four resolved signature abilities.

    Raises:
        MechanicsError: If a signature reference is missing or malformed.

    """
    hero_id = hero.get("id")
    if not isinstance(hero_id, int):
        raise MechanicsError("hero asset is missing a numeric id")
    by_class = {
        str(asset["class_name"]): asset
        for asset in assets
        if isinstance(asset.get("class_name"), str)
    }
    references = hero.get("items")
    if not isinstance(references, dict):
        raise MechanicsError(f"hero {hero_id} has no signature ability mapping")
    abilities: list[dict[str, Any]] = []
    for slot in range(1, 5):
        class_name = references.get(f"signature{slot}")
        if not isinstance(class_name, str) or class_name not in by_class:
            raise MechanicsError(f"hero {hero_id} is missing signature ability {slot}")
        record = extract_asset_mechanics(by_class[class_name])
        record["slot"] = slot
        abilities.append(record)
    result: dict[str, Any] = {
        "hero_id": hero_id,
        "name": clean_mechanical_text(hero.get("name")) or f"Hero {hero_id}",
        "class_name": str(hero.get("class_name") or ""),
        "description": normalize_hero_description(hero.get("description")),
        "abilities": abilities,
    }
    for field in ("scaling_stats", "starting_stats", "level_info", "cost_bonuses"):
        value = hero.get(field)
        if _is_populated(value):
            result[field] = normalize_mechanical_value(value)
    result["mechanics_sha256"] = sha256_json(result)
    return result


_THREAT_RESPONSE_PHRASES = {
    "hard_control": (
        "debuff immunity",
        "remove all negative",
        "unstoppable",
        "control immunity",
    ),
    "healing": ("healing reduction", "reduce healing", "anti-heal"),
    "bullet_pressure": (
        "bullet resist",
        "bullet shield",
        "weapon damage resistance",
    ),
    "spirit_burst": ("spirit resist", "spirit shield"),
    "mobility_denial": ("slow immunity", "movement slow resistance"),
}


def classify_item_threat_responses(asset: dict[str, Any]) -> frozenset[str]:
    """Map only explicit current item mechanics to conservative threat classes.

    Returns:
        Threats for which the asset text contains a direct response mechanic.

    """
    normalized = canonical_mechanics_text(_observed_item_mechanics(asset))
    responses = {
        threat
        for threat, phrases in _THREAT_RESPONSE_PHRASES.items()
        if any(phrase in normalized for phrase in phrases)
    }
    if "ally" in normalized and any(
        phrase in normalized for phrase in ("shield", "heal", "resist")
    ):
        responses.add("ally_protection")
    return frozenset(responses)


_OBSERVED_ITEM_THREAT_PHRASES = {
    "bullet_pressure": ("bullet damage", "weapon damage"),
    "spirit_pressure": ("spirit damage", "spirit power"),
    "control": ("apply a stun", "silence", "immobilize", "rooted"),
    "mobility_escape": ("dash", "teleport", "leap", "move speed"),
    "ally_protection": (
        "target ally",
        "allied target",
        "shield an ally",
        "ally barrier",
    ),
}


def _active_property_mechanics(asset: dict[str, Any]) -> dict[str, Any]:
    raw_properties = asset.get("properties")
    if not isinstance(raw_properties, dict):
        return {}
    active: dict[str, Any] = {}
    for name, raw_property in raw_properties.items():
        if not isinstance(raw_property, dict) or "value" not in raw_property:
            continue
        value = raw_property["value"]
        disabled_value = raw_property.get("disable_value")
        if disabled_value is not None and str(value) == str(disabled_value):
            continue
        if value is None or (
            isinstance(value, (str, int, float)) and str(value) in {"", "0", "0.0"}
        ):
            continue
        active[str(name)] = {
            key: raw_property[key]
            for key in (
                "css_class",
                "label",
                "postvalue_label",
                "provided_property_type",
                "value",
            )
            if key in raw_property
        }
    return active


def _observed_item_mechanics(asset: dict[str, Any]) -> dict[str, Any]:
    mechanics = extract_asset_mechanics(asset)
    observed = {
        key: mechanics[key]
        for key in (
            "description",
            "behaviour",
            "damage_type",
            "targeting",
            "weapon_info",
        )
        if key in mechanics
    }
    active_properties = _active_property_mechanics(asset)
    if active_properties:
        observed["properties"] = normalize_mechanical_value(active_properties)
    return observed


def classify_observed_item_threats(asset: dict[str, Any]) -> frozenset[str]:
    """Classify only explicit threat mechanics on an observed enemy item.

    Returns:
        Conservative threat labels supported by the pinned item text.

    """
    normalized = canonical_mechanics_text(_observed_item_mechanics(asset))
    threats = {
        threat
        for threat, phrases in _OBSERVED_ITEM_THREAT_PHRASES.items()
        if any(phrase in normalized for phrase in phrases)
    }
    healing_response = any(
        phrase in normalized
        for phrase in ("healing reduction", "reduce healing", "anti-heal")
    )
    healing = any(
        phrase in normalized
        for phrase in ("restore health", "health regen", "healing amp", "heal an ally")
    )
    if healing and not healing_response:
        threats.add("healing")
    return frozenset(threats)


def canonical_mechanics_text(mechanics: dict[str, Any]) -> str:
    """Flatten normalized mechanics for conservative phrase classification.

    Returns:
        Case-folded canonical JSON text.

    """
    return json.dumps(
        mechanics,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).casefold()


def ability_definitions_from_kit(
    kit: dict[str, Any],
) -> dict[int, AbilityDefinition]:
    """Resolve signature abilities and explicit qualifiers from a kit record.

    Returns:
        Definitions whose first unlock consumes the next level-granted unlock token.

    Raises:
        MechanicsError: If the kit's four abilities are incomplete.

    """
    raw_abilities = kit.get("abilities")
    if not isinstance(raw_abilities, list) or len(raw_abilities) != 4:
        raise MechanicsError("kit must contain four signature abilities")
    definitions: dict[int, AbilityDefinition] = {}
    for raw in raw_abilities:
        if not isinstance(raw, dict) or not isinstance(raw.get("id"), int):
            raise MechanicsError("kit contains an invalid signature ability")
        ability_id = int(raw["id"])
        normalized = canonical_mechanics_text(raw)
        qualifiers = frozenset(
            qualifier
            for qualifier in ("charged", "channeled", "airborne")
            if qualifier in normalized
        )
        raw_unlock_level = raw.get("unlock_level")
        unlock_level = (
            int(raw_unlock_level)
            if isinstance(raw_unlock_level, int) and raw_unlock_level > 0
            else 1
        )
        raw_upgrade_costs = raw.get("upgrade_costs")
        upgrade_costs = (
            tuple(int(cost) for cost in raw_upgrade_costs)
            if isinstance(raw_upgrade_costs, list)
            and raw_upgrade_costs
            and all(isinstance(cost, int) and cost > 0 for cost in raw_upgrade_costs)
            else DEFAULT_ABILITY_UPGRADE_COSTS
        )
        definitions[ability_id] = AbilityDefinition(
            ability_id,
            unlock_level=unlock_level,
            upgrade_costs=upgrade_costs,
            qualifiers=qualifiers,
            ultimate=int(raw.get("slot") or 0) == 4,
        )
    return definitions


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
        self._validate_acyclic()

    @classmethod
    def from_assets(cls, assets: list[dict[str, Any]]) -> ItemGraph:
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
            raw_components = asset.get("component_items") or []
            if not isinstance(raw_components, list) or not all(
                isinstance(component, str) for component in raw_components
            ):
                raise MechanicsError(f"item {item_id} has malformed components")
            max_count = asset.get("max_count")
            nodes[item_id] = ItemNode(
                item_id=item_id,
                class_name=class_name,
                name=str(asset.get("name") or class_name),
                cost=max(0, int(asset.get("cost") or 0)),
                slot=str(asset.get("item_slot_type") or "unknown").casefold(),
                tier=int(asset.get("item_tier") or 0),
                component_classes=tuple(raw_components),
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
        ordered: list[int] = []
        seen: set[int] = set()

        def collect(current: int) -> None:
            for component_id in self.components[current]:
                collect(component_id)
                if component_id not in seen:
                    seen.add(component_id)
                    ordered.append(component_id)

        collect(item_id)
        return tuple(ordered)

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
    values: dict[str, Any]


@dataclass(frozen=True)
class CategoryBonusTable:
    categories: dict[str, tuple[CategoryBonus, ...]]

    @classmethod
    def from_asset(cls, asset: dict[str, Any]) -> CategoryBonusTable:
        raw = asset.get("cost_bonuses")
        if not isinstance(raw, dict):
            raise MechanicsError("authoritative cost_bonuses are missing")
        categories: dict[str, tuple[CategoryBonus, ...]] = {}
        for category, rows in raw.items():
            categories[str(category).casefold()] = _category_bonuses(category, rows)
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


def _category_bonus_rows(category: object, rows: object) -> list[object]:
    if isinstance(rows, dict):
        return [
            {"threshold": threshold, "value": value}
            for threshold, value in rows.items()
        ]
    if not isinstance(rows, list):
        raise MechanicsError(f"malformed {category} cost bonuses")
    return cast("list[object]", rows)


def _category_bonus(category: object, row: object) -> CategoryBonus:
    if not isinstance(row, dict):
        raise MechanicsError(f"malformed {category} cost bonus")
    threshold = row.get("gold_threshold", row.get("threshold", row.get("cost")))
    if isinstance(threshold, str) and threshold.isdigit():
        threshold = int(threshold)
    if not isinstance(threshold, int) or threshold < 0:
        raise MechanicsError(f"invalid {category} bonus threshold")
    return CategoryBonus(
        threshold,
        normalize_mechanical_value({
            key: value
            for key, value in row.items()
            if key not in {"gold_threshold", "threshold", "cost"}
        }),
    )


def _category_bonuses(category: object, rows: object) -> tuple[CategoryBonus, ...]:
    ordered = sorted(
        (
            _category_bonus(category, row)
            for row in _category_bonus_rows(category, rows)
        ),
        key=lambda bonus: bonus.threshold,
    )
    if len({bonus.threshold for bonus in ordered}) != len(ordered):
        raise MechanicsError(f"duplicate {category} bonus threshold")
    return tuple(ordered)


@dataclass(frozen=True)
class AbilityDefinition:
    ability_id: int
    unlock_level: int
    upgrade_costs: tuple[int, ...] = DEFAULT_ABILITY_UPGRADE_COSTS
    qualifiers: frozenset[str] = frozenset()
    ultimate: bool = False


@dataclass(frozen=True)
class AbilityAction:
    level: int
    ability_id: int


@dataclass(frozen=True)
class AbilityTimelineStep:
    level: int
    ability_id: int
    rank: int
    cost: int
    currency: str
    ap_remaining: int
    unlocks_remaining: int


def _level_rows(level_info: object) -> list[tuple[object, object]]:
    if isinstance(level_info, dict):
        return list(level_info.items())
    if isinstance(level_info, list):
        return [
            (row.get("level"), row) if isinstance(row, dict) else (None, row)
            for row in level_info
        ]
    raise MechanicsError("hero level_info must be an object or list")


def _level_grant(raw_level: object, row: object) -> tuple[int, tuple[int, int]]:
    if not isinstance(row, dict):
        raise MechanicsError("level_info row is missing level")
    level = raw_level
    if isinstance(level, str) and level.isdigit():
        level = int(level)
    if not isinstance(level, int):
        raise MechanicsError("level_info row is missing level")
    currencies = row.get("bonus_currencies", [])
    if not isinstance(currencies, list) or not all(
        isinstance(currency, str) for currency in currencies
    ):
        raise MechanicsError("level_info has malformed bonus currencies")
    explicit_ap = row.get("ability_points", row.get("ability_points_granted", 0))
    explicit_unlocks = row.get("ability_unlocks", 0)
    if (
        not isinstance(explicit_ap, int)
        or explicit_ap < 0
        or not isinstance(explicit_unlocks, int)
        or explicit_unlocks < 0
    ):
        raise MechanicsError("level_info has an invalid ability-point grant")
    ap = explicit_ap + sum(currency == "EAbilityPoints" for currency in currencies)
    unlocks = explicit_unlocks + sum(
        currency == "EAbilityUnlocks" for currency in currencies
    )
    return level, (unlocks, ap)


def _currency_grants_by_level(level_info: object) -> dict[int, tuple[int, int]]:
    result: dict[int, tuple[int, int]] = {}
    for raw_level, row in _level_rows(level_info):
        level, grant = _level_grant(raw_level, row)
        result[level] = grant
    if not result:
        raise MechanicsError("level_info contains no levels")
    return result


@dataclass
class _AbilityProgress:
    ranks: dict[int, int]
    ap: int = 0
    unlocks: int = 0
    current_level: int = 0


def _advance_ability_level(
    progress: _AbilityProgress,
    grants: dict[int, tuple[int, int]],
    level: int,
) -> None:
    for current in range(progress.current_level + 1, level + 1):
        unlock_grant, ap_grant = grants.get(current, (0, 0))
        progress.unlocks += unlock_grant
        progress.ap += ap_grant
    progress.current_level = level


def _apply_ability_action(
    progress: _AbilityProgress,
    definitions: dict[int, AbilityDefinition],
    action: AbilityAction,
) -> AbilityTimelineStep:
    definition = definitions.get(action.ability_id)
    if definition is None:
        raise MechanicsError(f"unknown ability {action.ability_id}")
    prior_rank = progress.ranks[action.ability_id]
    if prior_rank == 0:
        if action.level < definition.unlock_level:
            raise MechanicsError(
                f"ability {action.ability_id} unlocks at level {definition.unlock_level}"
            )
        cost = 1
        currency = "ability_unlock"
        if not progress.unlocks:
            raise MechanicsError(
                f"ability {action.ability_id} needs an unlock currency"
            )
        progress.unlocks -= 1
    else:
        cost_index = prior_rank - 1
        if cost_index >= len(definition.upgrade_costs):
            raise MechanicsError(f"ability {action.ability_id} is already maxed")
        cost = definition.upgrade_costs[cost_index]
        currency = "ability_points"
        if cost > progress.ap:
            raise MechanicsError(
                f"ability {action.ability_id} costs {cost} AP with only {progress.ap} available"
            )
        progress.ap -= cost
    progress.ranks[action.ability_id] = prior_rank + 1
    return AbilityTimelineStep(
        level=action.level,
        ability_id=action.ability_id,
        rank=prior_rank + 1,
        cost=cost,
        currency=currency,
        ap_remaining=progress.ap,
        unlocks_remaining=progress.unlocks,
    )


def validate_ability_timeline(
    definitions: dict[int, AbilityDefinition],
    level_info: object,
    actions: tuple[AbilityAction, ...],
) -> tuple[AbilityTimelineStep, ...]:
    """Simulate unlocks/upgrades against pinned levels and AP grants.

    Returns:
        Legal actions with exact AP balances.

    Raises:
        MechanicsError: If an action is unknown, too early, over-upgraded, or unaffordable.

    """
    grants = _currency_grants_by_level(level_info)
    if tuple(actions) != tuple(sorted(actions, key=lambda action: action.level)):
        raise MechanicsError("ability actions must be ordered by level")
    progress = _AbilityProgress(dict.fromkeys(definitions, 0))
    result: list[AbilityTimelineStep] = []
    for action in actions:
        if action.level not in grants:
            raise MechanicsError(f"ability action uses unknown level {action.level}")
        _advance_ability_level(progress, grants, action.level)
        result.append(_apply_ability_action(progress, definitions, action))
    return tuple(result)


def schedule_ability_path(
    definitions: dict[int, AbilityDefinition],
    level_info: object,
    ability_ids: tuple[int, ...],
) -> tuple[AbilityAction, ...]:
    """Place an observed upgrade sequence at its earliest legal pinned levels.

    Returns:
        Nondecreasing level actions that consume the real unlock/AP currencies.

    Raises:
        MechanicsError: If no current level can realize an observed action.

    """
    levels = tuple(sorted(_currency_grants_by_level(level_info)))
    if not levels:
        raise MechanicsError("cannot schedule abilities without current levels")
    actions: list[AbilityAction] = []
    minimum_level = levels[0]
    for ability_id in ability_ids:
        scheduled = False
        for level in levels:
            if level < minimum_level:
                continue
            candidate = (*actions, AbilityAction(level, ability_id))
            try:
                validate_ability_timeline(definitions, level_info, candidate)
            except MechanicsError:
                continue
            actions.append(AbilityAction(level, ability_id))
            minimum_level = level
            scheduled = True
            break
        if not scheduled:
            raise MechanicsError(
                f"ability path cannot legally schedule ability {ability_id}"
            )
    return tuple(actions)


@dataclass(frozen=True)
class InventoryState:
    owned: tuple[int, ...] = ()
    unlocked_flex_slots: int = 0

    def __post_init__(self) -> None:
        """Validate the flex-slot domain.

        Raises:
            MechanicsError: If the state claims an impossible flex count.

        """
        if not 0 <= self.unlocked_flex_slots <= MAX_FLEX_SLOTS:
            raise MechanicsError("unlocked flex slots must be between zero and three")


def purchase_item(
    graph: ItemGraph,
    state: InventoryState,
    item_id: int,
    *,
    required_flex_slots: int = 0,
) -> InventoryState:
    """Apply one legal purchase including direct component consumption.

    Returns:
        The post-purchase inventory.

    Raises:
        MechanicsError: If availability, duplicate, flex, slot, or active limits fail.

    """
    node = graph.require(item_id)
    if required_flex_slots > state.unlocked_flex_slots:
        raise MechanicsError("purchase requires unavailable flex capacity")
    owned = list(state.owned)
    count = owned.count(item_id)
    if (node.unique and count) or count >= node.max_count:
        raise MechanicsError(f"item {node.name} exceeds its ownership limit")
    for component_id in graph.components[item_id]:
        if component_id in owned:
            owned.remove(component_id)
    owned.append(item_id)
    capacity = BASE_INVENTORY_SLOTS + state.unlocked_flex_slots
    if len(owned) > capacity:
        raise MechanicsError(f"purchase exceeds {capacity} available item slots")
    active_count = sum(graph.require(owned_id).active for owned_id in owned)
    if active_count > MAX_ACTIVE_ITEMS:
        raise MechanicsError("purchase exceeds four active-item bindings")
    return InventoryState(tuple(owned), state.unlocked_flex_slots)


@dataclass(frozen=True)
class _ComponentPlan:
    item_ids: tuple[int, ...]
    dependencies: tuple[frozenset[int], ...]


class _ComponentPlanner:
    def __init__(self, graph: ItemGraph) -> None:
        self.graph = graph
        self.planned_ids: list[int] = []
        self.dependencies: list[set[int]] = []
        self.consumed_by: dict[int, int] = {}
        self.owned_actions: dict[int, int] = {}
        self.last_action_by_item: dict[int, int] = {}
        self.state = InventoryState()

    def plan(self, item_id: int) -> int:
        if item_id in self.state.owned:
            try:
                return self.owned_actions[item_id]
            except KeyError as error:
                raise MechanicsError(
                    f"owned item {item_id} has no planned purchase action"
                ) from error

        component_actions = tuple(
            self.plan(component_id) for component_id in self.graph.components[item_id]
        )
        action_index = len(self.planned_ids)
        action_dependencies = set(component_actions)
        previous_action = self.last_action_by_item.get(item_id)
        if previous_action is not None:
            consumer = self.consumed_by.get(previous_action)
            if consumer is None:
                raise MechanicsError(
                    f"item {item_id} cannot be rebought before its prior copy is consumed"
                )
            action_dependencies.add(consumer)

        missing = [
            component_id
            for component_id in self.graph.components[item_id]
            if component_id not in self.state.owned
        ]
        if missing:
            raise MechanicsError(
                f"planned item {item_id} is missing components {missing}"
            )
        self.state = purchase_item(self.graph, self.state, item_id)
        self.planned_ids.append(item_id)
        self.dependencies.append(action_dependencies)
        for component_id, component_action in zip(
            self.graph.components[item_id], component_actions, strict=True
        ):
            self.consumed_by[component_action] = action_index
            self.owned_actions.pop(component_id, None)
        self.owned_actions[item_id] = action_index
        self.last_action_by_item[item_id] = action_index
        return action_index

    def build(self, target_ids: tuple[int, ...]) -> _ComponentPlan:
        final_actions: list[int] = []
        for item_id in target_ids:
            action_index = self.plan(item_id)
            if action_index in final_actions:
                raise MechanicsError(f"final item {item_id} was already scheduled")
            if final_actions:
                self.dependencies[action_index].add(final_actions[-1])
            final_actions.append(action_index)
        if set(self.state.owned) != set(target_ids):
            raise MechanicsError(
                "planned component path does not end in final inventory"
            )
        return _ComponentPlan(
            tuple(self.planned_ids),
            tuple(frozenset(required) for required in self.dependencies),
        )


def _plan_component_actions(
    graph: ItemGraph, target_ids: tuple[int, ...]
) -> _ComponentPlan:
    return _ComponentPlanner(graph).build(target_ids)


class _ComponentScheduleSearch:
    def __init__(
        self,
        graph: ItemGraph,
        plan: _ComponentPlan,
        target_ids: tuple[int, ...],
        priorities: Mapping[int, tuple[float, float, int]],
    ) -> None:
        self.graph = graph
        self.plan = plan
        self.target_ids = target_ids
        self.priorities = priorities
        self.failed_states: set[tuple[frozenset[int], tuple[int, ...], int]] = set()

    def _ready_actions(self, completed: frozenset[int]) -> list[int]:
        return sorted(
            (
                index
                for index, required in enumerate(self.plan.dependencies)
                if index not in completed and required <= completed
            ),
            key=lambda index: (
                *self.priorities.get(
                    self.plan.item_ids[index],
                    (
                        float("inf"),
                        float("inf"),
                        self.plan.item_ids[index],
                    ),
                ),
                index,
            ),
        )

    def search(
        self,
        completed: frozenset[int],
        state: InventoryState,
    ) -> tuple[int, ...] | None:
        if len(completed) == len(self.plan.item_ids):
            return () if set(state.owned) == set(self.target_ids) else None
        state_key = (
            completed,
            tuple(sorted(state.owned)),
            state.unlocked_flex_slots,
        )
        if state_key in self.failed_states:
            return None
        for action_index in self._ready_actions(completed):
            item_id = self.plan.item_ids[action_index]
            if any(
                component_id not in state.owned
                for component_id in self.graph.components[item_id]
            ):
                continue
            try:
                next_state = purchase_item(self.graph, state, item_id)
            except MechanicsError:
                continue
            suffix = self.search(completed | {action_index}, next_state)
            if suffix is not None:
                return (action_index, *suffix)
        self.failed_states.add(state_key)
        return None


def _search_component_schedule(
    graph: ItemGraph,
    plan: _ComponentPlan,
    target_ids: tuple[int, ...],
    priorities: Mapping[int, tuple[float, float, int]],
) -> tuple[int, ...] | None:
    return _ComponentScheduleSearch(graph, plan, target_ids, priorities).search(
        frozenset(), InventoryState()
    )


def schedule_component_path(
    graph: ItemGraph,
    targets: Sequence[int],
    priorities: Mapping[int, tuple[float, float, int]],
) -> tuple[int, ...]:
    """Schedule a chronological, legal purchase path for a final inventory.

    Purchase timing ranks every action, while component dependencies, final-item
    order, inventory capacity, active-item limits, and consumed-component rebuys
    remain hard constraints.

    Returns:
        Item IDs in executable left-to-right purchase order.

    Raises:
        MechanicsError: If no legal schedule reaches the requested inventory.

    """
    target_ids = tuple(targets)
    if not target_ids:
        raise MechanicsError("component schedule has no final inventory targets")
    if len(set(target_ids)) != len(target_ids):
        raise MechanicsError("component schedule final inventory contains duplicates")
    for item_id in target_ids:
        graph.require(item_id)

    plan = _plan_component_actions(graph, target_ids)
    scheduled_actions = _search_component_schedule(graph, plan, target_ids, priorities)
    if scheduled_actions is None:
        names = ", ".join(graph.require(item_id).name for item_id in target_ids)
        raise MechanicsError(f"no legal chronological component schedule for {names}")
    return tuple(plan.item_ids[index] for index in scheduled_actions)


def sell_item(graph: ItemGraph, state: InventoryState, item_id: int) -> InventoryState:
    """Sell one currently owned item.

    Returns:
        The post-sale inventory.

    Raises:
        MechanicsError: If the item is unknown or not owned.

    """
    graph.require(item_id)
    owned = list(state.owned)
    if item_id not in owned:
        raise MechanicsError(f"cannot sell unowned item {item_id}")
    owned.remove(item_id)
    return InventoryState(tuple(owned), state.unlocked_flex_slots)


def validate_imbue(
    definitions: dict[int, AbilityDefinition],
    learned_abilities: set[int],
    ability_id: int,
    *,
    required_qualifier: str | None = None,
    allow_ultimate: bool = True,
) -> None:
    """Validate an item-to-ability imbue against current learned mechanics.

    Raises:
        MechanicsError: If the target is unlearned, disallowed, or unqualified.

    """
    definition = definitions.get(ability_id)
    if definition is None or ability_id not in learned_abilities:
        raise MechanicsError("imbue target must be a current learned ability")
    if definition.ultimate and not allow_ultimate:
        raise MechanicsError("this item cannot imbue an ultimate ability")
    if required_qualifier and required_qualifier not in definition.qualifiers:
        raise MechanicsError(f"ability {ability_id} is not proven {required_qualifier}")
