from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from .snapshot import sha256_json

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


def _valid_tag_value(class_name: object, label: object, tag_id: object) -> bool:
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
    def from_assets(cls, values: list[dict[str, Any]]) -> BuildTagCatalog:
        tags: list[BuildTag] = []
        for value in values:
            class_name = value.get("class_name")
            label = value.get("label")
            tag_id = value.get("id")
            if not _valid_tag_value(class_name, label, tag_id):
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

    def as_list(self) -> list[dict[str, str | int]]:
        return [
            {
                "class_name": tag.class_name,
                "label": tag.label,
                "id": tag.tag_id,
            }
            for tag in sorted(self.tags, key=lambda tag: tag.class_name)
        ]


@dataclass(frozen=True)
class BuildTagSelection:
    tag_ids: tuple[int, int, int]
    class_names: tuple[str, str, str]
    labels: tuple[str, str, str]
    archetype: str


def _asset_text(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(f"{key} {_asset_text(nested)}" for key, nested in value.items())
    if isinstance(value, list):
        return " ".join(_asset_text(nested) for nested in value)
    if isinstance(value, str):
        return value
    return ""


def _function_class(asset: dict[str, Any]) -> str:
    text = _asset_text(asset).casefold()
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


def select_build_tags(
    core_item_ids: tuple[int, ...],
    assets: list[dict[str, Any]],
    catalog: BuildTagCatalog,
) -> BuildTagSelection:
    """Select one axis, function, and conservative audience tag.

    Returns:
        The selected tag identities and player-facing archetype.

    Raises:
        BuildTagError: If CORE references an item missing from the pinned assets.

    """
    by_id = {
        int(asset["id"]): asset for asset in assets if isinstance(asset.get("id"), int)
    }
    if not core_item_ids or any(item_id not in by_id for item_id in core_item_ids):
        raise BuildTagError("CORE items are missing from pinned assets")
    axis_cost = dict.fromkeys(AXIS_CLASSES, 0)
    function_cost = dict.fromkeys(FUNCTION_CLASSES, 0)
    slot_class = {
        "weapon": "citadel_build_tag_weapon",
        "spirit": "citadel_build_tag_spirit",
        "vitality": "citadel_build_tag_vitality",
    }
    for item_id in core_item_ids:
        asset = by_id[item_id]
        cost = int(asset.get("cost") or 0)
        axis = slot_class.get(str(asset.get("item_slot_type") or "").casefold())
        if axis is not None:
            axis_cost[axis] += cost
        function_cost[_function_class(asset)] += cost
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
    axis = catalog.require(axis_class)
    function = catalog.require(function_class)
    complexity = catalog.require(COMPLEXITY_CLASS)
    archetype = (
        f"{axis.label} Damage"
        if function_class == "citadel_build_tag_damage"
        else f"{function.label} / {axis.label}"
    )
    return BuildTagSelection(
        (axis.tag_id, function.tag_id, complexity.tag_id),
        (axis.class_name, function.class_name, complexity.class_name),
        (axis.label, function.label, complexity.label),
        archetype,
    )
