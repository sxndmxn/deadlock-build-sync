from __future__ import annotations

import math
from collections import Counter
from dataclasses import replace

from .ability_order import AbilityPath
from .artifact_bundle_types import (
    _CORE_CATEGORY_NAME,
    ArtifactBundleError,
)
from .build_evidence import (
    MAXIMUM_CORE_ITEM_COUNT,
    MINIMUM_BACKBONE_ITEM_COUNT,
    HeroBuildEvidence,
)
from .policy import BuildPolicy, NodeKind
from .purchase_guide import (
    GuideCategory,
    GuideItem,
    guide_item_from_evidence,
    standard_category_description,
)
from .value_validation import integer, object_dict, object_list, object_rows


def _policy_core(policy: BuildPolicy) -> tuple[int, ...]:
    nodes = {node.node_id: node for node in policy.nodes}
    current = policy.entry
    visited: set[str] = set()
    item_ids: list[int] = []
    while current not in visited:
        visited.add(current)
        node = nodes.get(current)
        if node is None:
            raise ArtifactBundleError(
                f"hero {policy.hero_id} policy has a dangling default path"
            )
        if node.kind == NodeKind.END:
            break
        if node.kind == NodeKind.CHOICE:
            defaults = [branch for branch in node.branches if branch.is_default]
            if len(defaults) != 1:
                raise ArtifactBundleError(
                    f"hero {policy.hero_id} artifact core choice has no unique default"
                )
            current = defaults[0].next_id
            continue
        if node.kind != NodeKind.PURCHASE or node.item_id is None:
            raise ArtifactBundleError(
                f"hero {policy.hero_id} artifact core is not a purchase-only path"
            )
        item_ids.append(node.item_id)
        if node.next_id is None:
            raise ArtifactBundleError(
                f"hero {policy.hero_id} policy core ends without an end node"
            )
        current = node.next_id
    else:
        raise ArtifactBundleError(f"hero {policy.hero_id} policy core contains a cycle")
    if not MINIMUM_BACKBONE_ITEM_COUNT <= len(item_ids) <= MAXIMUM_CORE_ITEM_COUNT:
        raise ArtifactBundleError(
            f"hero {policy.hero_id} artifact core has an unsupported item count"
        )
    return tuple(item_ids)


def _optional_int(value: object, label: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ArtifactBundleError(f"artifact projection has an invalid {label}")
    return value


def _check_projected_annotation(projected: GuideItem, annotation: object) -> None:
    """Confirm a stored item annotation still matches its evidence.

    Raises:
        ArtifactBundleError: If the annotation is absent or stale.

    """
    if not isinstance(annotation, str):
        raise ArtifactBundleError("artifact projection has no item annotation")
    if annotation != projected.annotation:
        raise ArtifactBundleError(
            f"artifact projection item {projected.item_id} has a stale annotation"
        )


def _guide_item(
    value: object,
    *,
    evidence: HeroBuildEvidence,
    expected_tier: int | None,
) -> GuideItem:
    if not isinstance(value, dict):
        raise ArtifactBundleError("artifact projection contains a malformed item")
    item_id = value.get("item_id")
    name = value.get("item")
    if not isinstance(item_id, int) or item_id <= 0:
        raise ArtifactBundleError("artifact projection contains an incomplete item")
    if not isinstance(name, str) or not name.strip():
        raise ArtifactBundleError("artifact projection contains an incomplete item")
    item_evidence = next(
        (item for item in evidence.items if item.item_id == item_id),
        None,
    )
    if item_evidence is None or item_evidence.item != name.strip():
        raise ArtifactBundleError(
            f"hero {evidence.hero_id} projection item {item_id} conflicts with build evidence"
        )
    if expected_tier is not None and item_evidence.tier != expected_tier:
        raise ArtifactBundleError(
            f"hero {evidence.hero_id} projection item {item_id} has the wrong tier"
        )
    projected = replace(
        guide_item_from_evidence(item_evidence),
        required_flex_slots=_optional_int(
            value.get("required_flex_slots"), "flex-slot requirement"
        ),
        sell_priority=_optional_int(value.get("sell_priority"), "sell priority"),
        imbue_target_ability_id=_optional_int(
            value.get("imbue_target_ability_id"), "imbue target"
        ),
    )
    _check_projected_annotation(projected, value.get("annotation"))
    return projected


type _CategorySpec = tuple[str, bool, int, int, int | None]


def _projection_category_rows(
    hero: dict[str, object],
    expected: tuple[_CategorySpec, ...],
    hero_id: int,
) -> list[object]:
    projection = object_dict(hero.get("projection"))
    rows = object_list(projection.get("categories")) if projection is not None else None
    if rows is None or len(rows) != len(expected):
        raise ArtifactBundleError(
            f"hero {hero_id} artifact projection has the wrong row count"
        )
    return rows


def _projected_category(
    raw: object,
    spec: _CategorySpec,
    *,
    evidence: HeroBuildEvidence,
) -> tuple[GuideCategory, tuple[GuideItem, ...]]:
    name, optional, minimum, maximum, expected_tier = spec
    raw_items = raw.get("items") if isinstance(raw, dict) else None
    if (
        not isinstance(raw, dict)
        or raw.get("name") != name
        or raw.get("optional") is not optional
        or not isinstance(raw_items, list)
        or not minimum <= len(raw_items) <= maximum
    ):
        raise ArtifactBundleError(
            f"hero {evidence.hero_id} artifact row {name} is malformed"
        )
    items = tuple(
        _guide_item(item, evidence=evidence, expected_tier=expected_tier)
        for item in raw_items
    )
    if name != _CORE_CATEGORY_NAME and len({item.item_id for item in items}) != len(
        items
    ):
        raise ArtifactBundleError(
            f"hero {evidence.hero_id} artifact row {name} contains duplicates"
        )
    category = GuideCategory(
        name,
        items,
        description=standard_category_description(name) or "",
        optional=optional,
    )
    raw_width = raw.get("width")
    raw_height = raw.get("height")
    valid_width = isinstance(raw_width, (int, float)) and not isinstance(
        raw_width, bool
    )
    valid_height = isinstance(raw_height, (int, float)) and not isinstance(
        raw_height, bool
    )
    if not (
        valid_width
        and valid_height
        and math.isclose(float(raw_width), category.width)
        and math.isclose(float(raw_height), category.height)
    ):
        raise ArtifactBundleError(
            f"hero {evidence.hero_id} artifact row {name} has invalid dimensions"
        )
    return category, items


def _final_core_items(
    items: tuple[GuideItem, ...],
    core_path_ids: tuple[int, ...],
    policy_core_ids: tuple[int, ...],
    hero_id: int,
) -> tuple[GuideItem, ...]:
    if tuple(item.item_id for item in items) != core_path_ids:
        raise ArtifactBundleError(
            f"hero {hero_id} projection CORE path differs from component-expanded evidence"
        )
    by_id = {item.item_id: item for item in items}
    if not set(policy_core_ids) <= set(by_id):
        raise ArtifactBundleError(
            f"hero {hero_id} projection CORE path omits final items"
        )
    return tuple(by_id[item_id] for item_id in policy_core_ids)


def _validate_projected_item_sets(
    core_items: tuple[GuideItem, ...],
    optional_core_items: tuple[GuideItem, ...],
    tiers: dict[int, tuple[GuideItem, ...]],
    policy_core_ids: tuple[int, ...],
    hero_id: int,
) -> None:
    if tuple(item.item_id for item in core_items) != policy_core_ids:
        raise ArtifactBundleError(
            f"hero {hero_id} projection core differs from its policy"
        )
    core_ids = {item.item_id for item in core_items}
    tier_ids = {item.item_id for tier_items in tiers.values() for item in tier_items}
    optional_ids = {item.item_id for item in optional_core_items}
    if core_ids & (tier_ids | optional_ids) or tier_ids & optional_ids:
        raise ArtifactBundleError(f"hero {hero_id} policy rows repeat items")


def _categories(
    hero: dict[str, object],
    policy: BuildPolicy,
    evidence: HeroBuildEvidence,
) -> tuple[
    tuple[GuideCategory, ...],
    tuple[GuideItem, ...],
    tuple[GuideItem, ...],
    dict[int, tuple[GuideItem, ...]],
]:
    policy_core_ids = _policy_core(policy)
    core_path_ids = (
        evidence.sequence_policy.default_path
        if evidence.sequence_policy is not None
        else policy_core_ids
    )
    expected_rows: list[_CategorySpec] = [
        (_CORE_CATEGORY_NAME, False, len(core_path_ids), len(core_path_ids), None)
    ]
    if policy.core_alternatives:
        expected_rows.append((
            "OPTIONAL CORE",
            True,
            len(policy.core_alternatives),
            10,
            None,
        ))
    expected_rows.extend((f"TIER {tier}", True, 1, 10, tier) for tier in range(1, 5))
    expected = tuple(expected_rows)
    raw_categories = _projection_category_rows(hero, expected, policy.hero_id)
    categories: list[GuideCategory] = []
    tiers: dict[int, tuple[GuideItem, ...]] = {}
    core_items: tuple[GuideItem, ...] = ()
    optional_core_items: tuple[GuideItem, ...] = ()
    for raw, spec in zip(raw_categories, expected, strict=True):
        category, items = _projected_category(
            raw,
            spec,
            evidence=evidence,
        )
        categories.append(category)
        if spec[0] == _CORE_CATEGORY_NAME:
            core_items = _final_core_items(
                items, core_path_ids, policy_core_ids, policy.hero_id
            )
        elif spec[0] == "OPTIONAL CORE":
            optional_core_items = items
        elif spec[4] is not None:
            tiers[spec[4]] = items
    if {item.item_id for item in optional_core_items} != {
        card.item_id for card in policy.core_alternatives
    }:
        raise ArtifactBundleError(
            f"hero {policy.hero_id} OPTIONAL CORE differs from policy cards"
        )
    _validate_projected_item_sets(
        core_items,
        optional_core_items,
        tiers,
        policy_core_ids,
        policy.hero_id,
    )
    return tuple(categories), core_items, optional_core_items, tiers


def _ability_projection(
    raw: dict[str, object], policy: BuildPolicy
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    steps = object_rows(raw.get("steps"))
    if steps is None or len(steps) != 16:
        raise ArtifactBundleError(
            f"hero {policy.hero_id} ability policy must contain 16 actions"
        )
    ability_ids: list[int] = []
    decision_support: list[int] = []
    for step in steps:
        ability_id = step.get("ability_id")
        support = step.get("decision_reached_support")
        if (
            not isinstance(ability_id, int)
            or not isinstance(support, int)
            or support <= 0
        ):
            raise ArtifactBundleError(
                f"hero {policy.hero_id} has a malformed ability action"
            )
        ability_ids.append(ability_id)
        decision_support.append(support)
    if len(Counter(ability_ids)) != 4 or any(
        count != 4 for count in Counter(ability_ids).values()
    ):
        raise ArtifactBundleError(
            f"hero {policy.hero_id} ability policy is not a complete four-rank path"
        )
    policy_abilities = tuple(
        node.ability_id
        for node in policy.ability_plan
        if node.kind == NodeKind.ABILITY and node.ability_id is not None
    )
    if tuple(ability_ids) != policy_abilities:
        raise ArtifactBundleError(
            f"hero {policy.hero_id} ability projection differs from its policy"
        )
    return tuple(ability_ids), tuple(decision_support)


def _ability_path(hero: dict[str, object], policy: BuildPolicy) -> AbilityPath:
    raw = object_dict(hero.get("ability_policy"))
    if raw is None or object_list(raw.get("steps")) is None:
        raise ArtifactBundleError(f"hero {policy.hero_id} has no ability policy")
    ability_ids, decision_support = _ability_projection(raw, policy)
    integer_fields = (
        "all_valid_telemetry_appearances",
        "complete_path_appearances",
        "final_branch_support",
    )
    if any(not isinstance(raw.get(field), int) for field in integer_fields):
        raise ArtifactBundleError(
            f"hero {policy.hero_id} ability policy has invalid support"
        )
    cohort_matches = integer(raw["all_valid_telemetry_appearances"])
    complete_matches = integer(raw["complete_path_appearances"])
    matches = integer(raw["final_branch_support"])
    rate = raw.get("observed_final_branch_outcome_rate")
    if cohort_matches <= 0 or complete_matches <= 0 or matches <= 0:
        raise ArtifactBundleError(
            f"hero {policy.hero_id} ability policy has incoherent support"
        )
    if matches > complete_matches or complete_matches > cohort_matches:
        raise ArtifactBundleError(
            f"hero {policy.hero_id} ability policy has incoherent support"
        )
    if not isinstance(rate, (int, float)) or not 0.0 <= float(rate) <= 1.0:
        raise ArtifactBundleError(
            f"hero {policy.hero_id} ability policy has incoherent support"
        )
    wins = round(float(rate) * matches)
    return AbilityPath(
        ability_ids=ability_ids,
        matches=matches,
        wins=wins,
        losses=matches - wins,
        cohort_matches=cohort_matches,
        complete_path_matches=complete_matches,
        decision_support=decision_support,
        selection=str(raw.get("selection") or "MOST_SUPPORTED_LEGAL_STATE"),
        filter_item_ids=tuple(
            item_id
            for item_id in object_list(raw.get("filter_item_ids")) or []
            if isinstance(item_id, int)
        ),
    )
