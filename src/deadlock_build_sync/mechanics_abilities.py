from __future__ import annotations

import math
from dataclasses import dataclass

from .mechanics_assets import DEFAULT_ABILITY_UPGRADE_COSTS, MechanicsError
from .mechanics_item_text import canonical_mechanics_text
from .value_validation import integer, object_rows


def _property_number(asset: dict[str, object], name: str) -> float | None:
    properties = asset.get("properties")
    if not isinstance(properties, dict):
        return None
    prop = properties.get(name)
    if not isinstance(prop, dict):
        return None
    value = prop.get("value")
    if not isinstance(value, (str, int, float)):
        return None
    try:
        number = float(value)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def ability_definitions_from_kit(
    kit: dict[str, object],
) -> dict[int, AbilityDefinition]:
    """Resolve signature abilities and explicit qualifiers from a kit record.

    Returns:
        Definitions whose first unlock consumes the next level-granted unlock token.

    Raises:
        MechanicsError: If the kit's four abilities are incomplete.

    """
    raw_abilities = object_rows(kit.get("abilities"))
    if raw_abilities is None or len(raw_abilities) != 4:
        raise MechanicsError("kit must contain four signature abilities")
    definitions: dict[int, AbilityDefinition] = {}
    for raw in raw_abilities:
        if not isinstance(raw.get("id"), int):
            raise MechanicsError("kit contains an invalid signature ability")
        ability_id = integer(raw["id"])
        normalized = canonical_mechanics_text(raw)
        qualifiers = frozenset(
            qualifier
            for qualifier in ("charged", "channeled", "airborne")
            if qualifier in normalized
            or (
                qualifier == "channeled"
                and (_property_number(raw, "AbilityChannelTime") or 0) > 0
            )
        )
        raw_unlock_level = raw.get("unlock_level")
        unlock_level = (
            raw_unlock_level
            if isinstance(raw_unlock_level, int) and raw_unlock_level > 0
            else 1
        )
        raw_upgrade_costs = raw.get("upgrade_costs")
        upgrade_costs = (
            tuple(integer(cost) for cost in raw_upgrade_costs)
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
            ultimate=integer(raw.get("slot"), default=0) == 4,
        )
    return definitions


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
