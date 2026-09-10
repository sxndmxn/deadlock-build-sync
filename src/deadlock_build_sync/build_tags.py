from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from .snapshot import sha256_json
from .value_validation import integer

if TYPE_CHECKING:
    from .purchase_guide import GuideItem

AXIS_CLASSES = (
    "citadel_build_tag_weapon",
    "citadel_build_tag_spirit",
    "citadel_build_tag_vitality",
)
FUNCTION_CLASSES = (
    "citadel_build_tag_damage",
    "citadel_build_tag_utility",
    "citadel_build_tag_healing",
    "citadel_build_tag_crowd_control",
    "citadel_build_tag_mobility",
    "citadel_build_tag_melee",
    "citadel_build_tag_headshots",
    "citadel_build_tag_debuff",
)
COMPLEXITY_CLASS = "citadel_build_tag_complexity_2"
COMPLEXITY_CLASSES = (
    "citadel_build_tag_complexity_1",
    COMPLEXITY_CLASS,
    "citadel_build_tag_complexity_3",
)
EXPECTED_CLASSES = frozenset((*AXIS_CLASSES, *FUNCTION_CLASSES, *COMPLEXITY_CLASSES))


class BuildTagError(ValueError):
    """Raised when the pinned build-tag taxonomy or selection is invalid."""


def _is_valid_tag_value(class_name: object, label: object, tag_id: object) -> bool:
    return (
        isinstance(class_name, str)
        and bool(class_name.strip())
        and isinstance(label, str)
        and bool(label.strip())
        and isinstance(tag_id, int)
        and not isinstance(tag_id, bool)
        and tag_id > 0
    )


@dataclass(frozen=True)
class BuildTag:
    class_name: str
    label: str
    tag_id: int


@dataclass(frozen=True)
class BuildTagCatalog:
    tags: tuple[BuildTag, ...]
    sha256: str

    @classmethod
    def from_assets(cls, values: list[dict[str, object]]) -> BuildTagCatalog:
        tags: list[BuildTag] = []
        for value in values:
            class_name = value.get("class_name")
            label = value.get("label")
            tag_id = value.get("id")
            if not _is_valid_tag_value(class_name, label, tag_id):
                raise BuildTagError("build-tag catalog contains a malformed tag")
            tags.append(
                BuildTag(
                    cast("str", class_name).strip(),
                    cast("str", label).strip(),
                    cast("int", tag_id),
                )
            )
        by_class = {tag.class_name: tag for tag in tags}
        if len(by_class) != len(tags):
            raise BuildTagError("build-tag catalog contains duplicate class names")
        if len({tag.tag_id for tag in tags}) != len(tags):
            raise BuildTagError("build-tag catalog contains duplicate IDs")
        if len(tags) != len(EXPECTED_CLASSES):
            raise BuildTagError("build-tag catalog must contain exactly 14 tags")
        missing = EXPECTED_CLASSES - set(by_class)
        if missing:
            raise BuildTagError(
                "build-tag catalog is missing: " + ", ".join(sorted(missing))
            )
        canonical = [
            {"class_name": tag.class_name, "label": tag.label, "id": tag.tag_id}
            for tag in sorted(tags, key=lambda tag: tag.class_name)
        ]
        return cls(tuple(tags), sha256_json(canonical))

    def require(self, class_name: str) -> BuildTag:
        try:
            return next(tag for tag in self.tags if tag.class_name == class_name)
        except StopIteration as error:
            raise BuildTagError(f"missing build tag {class_name}") from error


@dataclass(frozen=True)
class BuildTagSelection:
    tag_ids: tuple[int, int, int]
    class_names: tuple[str, str, str]
    labels: tuple[str, str, str]
    archetype: str


def _extract_asset_text(value: object) -> str:
    if isinstance(value, dict):
        return " ".join(
            f"{key} {_extract_asset_text(nested)}" for key, nested in value.items()
        )
    if isinstance(value, list):
        return " ".join(_extract_asset_text(nested) for nested in value)
    if isinstance(value, str):
        return value
    return ""


def _classify_build_function(asset: dict[str, object]) -> str:
    text = _extract_asset_text(asset).casefold()
    rules = (
        (
            "citadel_build_tag_debuff",
            ("healing reduction", "heal amp receive penalty", "anti-heal"),
        ),
        (
            "citadel_build_tag_headshots",
            ("headshot", "head shot"),
        ),
        (
            "citadel_build_tag_melee",
            ("melee", "heavy punch"),
        ),
        (
            "citadel_build_tag_crowd_control",
            ("stun", "immobil", "silence", "disarm", "knockdown", "slowpercent"),
        ),
        (
            "citadel_build_tag_mobility",
            ("move speed", "dash", "teleport", "leap", "sprint"),
        ),
        (
            "citadel_build_tag_healing",
            ("healing", "heal", "lifesteal", "health regen"),
        ),
        (
            "citadel_build_tag_utility",
            ("ally", "shield", "barrier", "cooldown", "active"),
        ),
    )
    for class_name, terms in rules:
        if any(term in text for term in terms):
            return class_name
    return "citadel_build_tag_damage"


def _find_first_maxed_ability_id(ability_path_ids: tuple[int, ...]) -> int:
    counts = Counter(ability_path_ids)
    if (
        len(ability_path_ids) != 16
        or len(counts) != 4
        or any(count != 4 for count in counts.values())
    ):
        raise BuildTagError("ability path is not a complete four-ability path")
    reached: Counter[int] = Counter()
    for ability_id in ability_path_ids:
        reached[ability_id] += 1
        if reached[ability_id] == 4:
            return ability_id
    raise BuildTagError("ability path does not max an ability")


def _select_core_icon_item(core_items: tuple[GuideItem, ...]) -> GuideItem:
    priority = {3: 0, 4: 1, 2: 2, 1: 3}
    candidates = tuple(item for item in core_items if item.tier in priority)
    if not candidates:
        raise BuildTagError("CORE has no supported item tier for its item icon")
    return min(candidates, key=lambda item: (priority[item.tier], item.item_id))


def _parse_asset_identity(asset: dict[str, object], *, kind: str) -> tuple[str, str]:
    class_name = asset.get("class_name")
    label = asset.get("name")
    if (
        not isinstance(class_name, str)
        or not class_name.strip()
        or not isinstance(label, str)
        or not label.strip()
    ):
        raise BuildTagError(f"selected {kind} icon has no asset identity")
    return class_name.strip(), label.strip()


def _classify_core_items(
    core_item_ids: tuple[int, ...],
    assets_by_id: dict[int, dict[str, object]],
) -> tuple[str, str]:
    axis_cost = dict.fromkeys(AXIS_CLASSES, 0)
    function_cost = dict.fromkeys(FUNCTION_CLASSES, 0)
    slot_class = {
        "weapon": "citadel_build_tag_weapon",
        "spirit": "citadel_build_tag_spirit",
        "vitality": "citadel_build_tag_vitality",
    }
    for item_id in core_item_ids:
        asset = assets_by_id[item_id]
        cost = integer(asset.get("cost"), default=0)
        axis = slot_class.get(str(asset.get("item_slot_type") or "").casefold())
        if axis is not None:
            axis_cost[axis] += cost
        function_cost[_classify_build_function(asset)] += cost
    axis_class = min(
        AXIS_CLASSES,
        key=lambda class_name: (-axis_cost[class_name], AXIS_CLASSES.index(class_name)),
    )
    function_class = min(
        FUNCTION_CLASSES,
        key=lambda class_name: (
            -function_cost[class_name],
            FUNCTION_CLASSES.index(class_name),
        ),
    )
    return axis_class, function_class


def select_build_tags(
    ability_path_ids: tuple[int, ...],
    core_items: tuple[GuideItem, ...],
    assets: list[dict[str, object]],
    catalog: BuildTagCatalog,
) -> BuildTagSelection:
    """Select automatic ability, stable CORE item, and build function icons.

    Returns:
        The selected tag identities and player-facing archetype.

    Raises:
        BuildTagError: If the ability path or CORE icon cannot be resolved.

    """
    by_id = {
        cast("int", asset["id"]): asset
        for asset in assets
        if isinstance(asset.get("id"), int)
    }
    core_item_ids = tuple(item.item_id for item in core_items)
    if not core_item_ids or any(item_id not in by_id for item_id in core_item_ids):
        raise BuildTagError("CORE items are missing from pinned assets")
    ability_id = _find_first_maxed_ability_id(ability_path_ids)
    ability_asset = by_id.get(ability_id)
    if ability_asset is None:
        raise BuildTagError("first-maxed ability is missing from pinned assets")
    icon_item = _select_core_icon_item(core_items)
    ability_class, ability_label = _parse_asset_identity(ability_asset, kind="ability")
    item_class, item_label = _parse_asset_identity(
        by_id[icon_item.item_id], kind="CORE item"
    )
    axis_class, function_class = _classify_core_items(core_item_ids, by_id)
    function = catalog.require(function_class)
    axis = catalog.require(axis_class)
    archetype = (
        f"{axis.label} Damage"
        if function_class == "citadel_build_tag_damage"
        else f"{function.label} / {axis.label}"
    )
    tag_ids = (ability_id, icon_item.item_id, function.tag_id)
    if len(set(tag_ids)) != 3:
        raise BuildTagError("selected build icons are not distinct")
    return BuildTagSelection(
        tag_ids,
        (ability_class, item_class, function.class_name),
        (ability_label, item_label, function.label),
        archetype,
    )
