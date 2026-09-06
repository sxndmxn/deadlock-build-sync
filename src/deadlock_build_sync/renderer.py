from __future__ import annotations

from dataclasses import dataclass

from .build_evidence import MAXIMUM_CORE_ITEM_COUNT, MINIMUM_BACKBONE_ITEM_COUNT
from .policy import (
    Branch,
    BuildPolicy,
    NodeKind,
    PolicyError,
    PolicyNode,
    ValidationContext,
    validate_policy,
)
from .purchase_guide import (
    CORE_CATEGORY_DESCRIPTION,
    OPTIONAL_CORE_CATEGORY_DESCRIPTION,
    TIER_CATEGORY_DESCRIPTION,
    GuideCategory,
    GuideItem,
    PurchaseGuide,
)
from .renderer_items import apply_sell_priorities as _apply_sell_priorities
from .renderer_items import branch_label as _branch_label
from .renderer_items import guide_item as _guide_item
from .renderer_items import (
    project_guide_item_policy_fields as _project_guide_item_policy_fields,
)
from .renderer_validation import validate_optional_annotation
from .snapshot import sha256_json
from .value_validation import integer


def _default_branch(node: PolicyNode) -> Branch:
    try:
        return next(branch for branch in node.branches if branch.is_default)
    except StopIteration as error:
        raise PolicyError(f"choice {node.node_id} has no default") from error


def _linear_projection(
    nodes: dict[str, PolicyNode],
    start: str,
) -> tuple[PolicyNode, ...]:
    result: list[PolicyNode] = []
    current = start
    seen: set[str] = set()
    while current not in seen:
        seen.add(current)
        node = nodes[current]
        result.append(node)
        if node.kind == NodeKind.END:
            break
        if node.kind in {NodeKind.CHOICE, NodeKind.OBJECTIVE_GATE}:
            current = _default_branch(node).next_id
        elif node.next_id is not None:
            current = node.next_id
        else:
            break
    return tuple(result)


@dataclass(frozen=True)
class ProjectionIdentity:
    hero_name: str
    hero_class_name: str
    client_version: int
    match_mode: str
    rank_identity: str


def _conditional_nodes(policy: BuildPolicy) -> dict[int, PolicyNode]:
    result: dict[int, PolicyNode] = {}
    for node in policy.nodes:
        if node.kind != NodeKind.PURCHASE or not node.optional:
            continue
        if node.item_id is None:
            raise PolicyError(f"optional purchase {node.node_id} has no item")
        if node.item_id in result:
            raise PolicyError(
                f"multiple conditional branches project item {node.item_id}"
            )
        validate_optional_annotation(node.annotation)
        result[node.item_id] = node
    return result


def _evidence_core_items(
    layout: PurchaseGuide,
    default_path: tuple[PolicyNode, ...],
) -> tuple[tuple[GuideItem, ...], set[int]]:
    source_core_ids = tuple(item.item_id for item in layout.core_items)
    core_purchase_items = layout.core_purchase_items or layout.core_items
    policy_core_ids = tuple(
        node.item_id
        for node in default_path
        if node.kind == NodeKind.PURCHASE and node.item_id is not None
    )
    valid = (
        MINIMUM_BACKBONE_ITEM_COUNT <= len(source_core_ids) <= MAXIMUM_CORE_ITEM_COUNT
        and policy_core_ids == source_core_ids
    )
    if not valid:
        raise PolicyError(
            "policy default path does not match the supported evidence core"
        )
    return core_purchase_items, {item.item_id for item in core_purchase_items}


def _project_conditional_item(
    item: GuideItem, conditional: dict[int, PolicyNode]
) -> GuideItem:
    node = conditional.get(item.item_id)
    if node is None:
        return item
    return _project_guide_item_policy_fields(
        item,
        required_flex_slots=node.required_flex_slots or None,
        sell_priority=node.sell_priority,
        imbue_target_ability_id=(
            node.imbue_target_ability_id or item.imbue_target_ability_id
        ),
    )


def _evidence_tiers(
    policy: BuildPolicy,
    layout: PurchaseGuide,
    core_purchase_ids: set[int],
) -> tuple[dict[int, tuple[GuideItem, ...]], set[int]]:
    if any(not 1 <= len(layout.tiers.get(tier, ())) <= 10 for tier in range(1, 5)):
        raise PolicyError("evidence projection requires 1–10 items in every tier")
    tier_item_ids = {item.item_id for items in layout.tiers.values() for item in items}
    if tier_item_ids & core_purchase_ids:
        raise PolicyError("evidence tier menus must not repeat CORE path items")
    conditional = _conditional_nodes(policy)
    missing_conditional = set(conditional) - tier_item_ids
    if missing_conditional:
        raise PolicyError(
            "conditional policy items are missing from tier menus: "
            + ", ".join(str(item_id) for item_id in sorted(missing_conditional))
        )
    tiers = {
        tier: tuple(_project_conditional_item(item, conditional) for item in items)
        for tier, items in layout.tiers.items()
    }
    return tiers, tier_item_ids


def _evidence_optional_core(
    policy: BuildPolicy,
    layout: PurchaseGuide,
    core_purchase_ids: set[int],
    tier_item_ids: set[int],
) -> tuple[GuideItem, ...]:
    card_by_item = {card.item_id: card for card in policy.core_alternatives}
    optional_core_ids = {item.item_id for item in layout.optional_core_items}
    if optional_core_ids != set(card_by_item):
        raise PolicyError(
            "OPTIONAL CORE evidence does not match the admitted policy cards"
        )
    if optional_core_ids & (core_purchase_ids | tier_item_ids):
        raise PolicyError("OPTIONAL CORE items must be disjoint from CORE and tiers")
    return tuple(
        _project_guide_item_policy_fields(
            item,
            required_flex_slots=None,
            sell_priority=None,
            imbue_target_ability_id=item.imbue_target_ability_id,
        )
        for item in layout.optional_core_items
    )


def _evidence_categories(
    core_purchase_items: tuple[GuideItem, ...],
    optional_core_items: tuple[GuideItem, ...],
    tiers: dict[int, tuple[GuideItem, ...]],
) -> tuple[GuideCategory, ...]:
    categories = [
        GuideCategory("CORE ITEMS", core_purchase_items, CORE_CATEGORY_DESCRIPTION)
    ]
    if optional_core_items:
        categories.append(
            GuideCategory(
                "OPTIONAL CORE",
                optional_core_items,
                OPTIONAL_CORE_CATEGORY_DESCRIPTION,
                optional=True,
            )
        )
    categories.extend(
        GuideCategory(
            f"TIER {tier}",
            tiers[tier],
            TIER_CATEGORY_DESCRIPTION,
            optional=True,
        )
        for tier in range(1, 5)
    )
    return tuple(categories)


def _project_evidence_layout(
    policy: BuildPolicy,
    identity: ProjectionIdentity,
    layout: PurchaseGuide,
    default_path: tuple[PolicyNode, ...],
) -> PurchaseGuide:
    core_purchase_items, core_purchase_ids = _evidence_core_items(layout, default_path)
    tiers, tier_item_ids = _evidence_tiers(policy, layout, core_purchase_ids)
    optional_core_items = _evidence_optional_core(
        policy, layout, core_purchase_ids, tier_item_ids
    )
    core_items = _apply_sell_priorities(layout.core_items, policy.nodes)
    core_purchase_items = _apply_sell_priorities(core_purchase_items, policy.nodes)
    categories = _evidence_categories(core_purchase_items, optional_core_items, tiers)
    return PurchaseGuide(
        hero_id=policy.hero_id,
        hero_name=identity.hero_name,
        hero_class_name=identity.hero_class_name,
        tiers=tiers,
        path_id=policy.path_id,
        path_label=policy.path_label,
        signature_item_ids=layout.signature_item_ids,
        summary=(
            f"{policy.strategic_role}; supported {len(layout.backbone_items)}-item "
            f"backbone observed in {layout.backbone_matches:,} player-matches "
            f"({layout.backbone_share * 100:.2f}%). OPTIONAL CORE and tier rows "
            "never enter the automatic Queue."
        ),
        categories=categories,
        snapshot_id=policy.snapshot_id,
        policy_id=policy.policy_id,
        client_version=identity.client_version,
        match_mode=identity.match_mode,
        rank_identity=identity.rank_identity,
        core_items=core_items,
        core_purchase_items=core_purchase_items,
        backbone_items=layout.backbone_items,
        optional_core_items=optional_core_items,
        core_alternatives=layout.core_alternatives,
        backbone_matches=layout.backbone_matches,
        backbone_share=layout.backbone_share,
        core_joint_matches=layout.core_joint_matches,
        core_joint_share=layout.core_joint_share,
        median_final_net_worth=layout.median_final_net_worth,
        core_target_cost=layout.core_target_cost,
        purchase_timing=layout.purchase_timing,
    )


def _default_core_items(
    policy: BuildPolicy,
    default_path: tuple[PolicyNode, ...],
    assets_by_id: dict[int, dict[str, object]],
) -> tuple[GuideItem, ...]:
    items = tuple(
        _guide_item(node, assets_by_id, policy, optional=False)
        for node in default_path
        if node.kind == NodeKind.PURCHASE
    )
    items = _apply_sell_priorities(items, policy.nodes)
    if not items:
        raise PolicyError("default policy path contains no purchase")
    return items


def _branch_category(
    branch: Branch,
    *,
    policy: BuildPolicy,
    nodes: dict[str, PolicyNode],
    assets_by_id: dict[int, dict[str, object]],
    default_item_ids: set[int],
) -> GuideCategory | None:
    if branch.is_default:
        return None
    path = _linear_projection(nodes, branch.next_id)
    items = tuple(
        _guide_item(node, assets_by_id, policy, optional=True)
        for node in path
        if node.kind == NodeKind.PURCHASE and node.item_id not in default_item_ids
    )
    items = _apply_sell_priorities(items, policy.nodes)
    if not items:
        return None
    return GuideCategory(
        _branch_label(branch),
        items,
        "Conditional branch; excluded from the default Queue.",
        optional=True,
    )


def _conditional_categories(
    policy: BuildPolicy,
    nodes: dict[str, PolicyNode],
    assets_by_id: dict[int, dict[str, object]],
    default_item_ids: set[int],
) -> list[GuideCategory]:
    categories: list[GuideCategory] = []
    seen: set[tuple[int, ...]] = set()
    for choice in policy.nodes:
        if choice.kind not in {NodeKind.CHOICE, NodeKind.OBJECTIVE_GATE}:
            continue
        for branch in choice.branches:
            category = _branch_category(
                branch,
                policy=policy,
                nodes=nodes,
                assets_by_id=assets_by_id,
                default_item_ids=default_item_ids,
            )
            item_ids = (
                tuple(item.item_id for item in category.items)
                if category is not None
                else ()
            )
            if category is not None and item_ids not in seen:
                seen.add(item_ids)
                categories.append(category)
    return categories


def _project_without_layout(
    policy: BuildPolicy,
    identity: ProjectionIdentity,
    nodes: dict[str, PolicyNode],
    default_path: tuple[PolicyNode, ...],
    assets_by_id: dict[int, dict[str, object]],
) -> PurchaseGuide:
    core_items = _default_core_items(policy, default_path, assets_by_id)
    categories: list[GuideCategory] = [
        GuideCategory(
            "CORE — DEFAULT QUEUE",
            core_items,
            "Minimal coherent default path. Recalculate when a conditional trigger applies.",
        )
    ]
    categories.extend(
        _conditional_categories(
            policy,
            nodes,
            assets_by_id,
            {item.item_id for item in core_items},
        )
    )
    tiers = {
        tier: tuple(
            item
            for category in categories
            for item in category.items
            if item.tier == tier
        )
        for tier in range(1, 5)
    }
    return PurchaseGuide(
        hero_id=policy.hero_id,
        hero_name=identity.hero_name,
        hero_class_name=identity.hero_class_name,
        tiers=tiers,
        path_id=policy.path_id,
        path_label=policy.path_label,
        summary=(
            f"{policy.strategic_role}; variant {policy.variant}. Rich policy guards and "
            "uncertainty remain in the sidecar; Steam receives the declared projection."
        ),
        categories=tuple(categories),
        snapshot_id=policy.snapshot_id,
        policy_id=policy.policy_id,
        client_version=identity.client_version,
        match_mode=identity.match_mode,
        rank_identity=identity.rank_identity,
    )


def project_policy_to_guide(
    policy: BuildPolicy,
    context: ValidationContext,
    *,
    assets: list[dict[str, object]],
    identity: ProjectionIdentity,
    layout_source: PurchaseGuide | None = None,
) -> PurchaseGuide:
    """Validate a rich policy and create its compact executable Steam projection.

    Returns:
        A guide whose Queue contains only the default path and whose alternatives are optional.

    """
    validate_policy(policy, context)
    nodes = {node.node_id: node for node in policy.nodes}
    assets_by_id = {
        integer(asset.get("id")): asset
        for asset in assets
        if isinstance(asset.get("id"), int)
    }
    default_path = _linear_projection(nodes, policy.entry)
    if layout_source is not None:
        return _project_evidence_layout(policy, identity, layout_source, default_path)
    return _project_without_layout(policy, identity, nodes, default_path, assets_by_id)


def projection_fingerprint(guide: PurchaseGuide) -> str:
    """Fingerprint all behavior emitted into the compact projection.

    Returns:
        SHA-256 of item/category semantics and identity fields.

    """
    return sha256_json({
        "hero_id": guide.hero_id,
        "path_id": guide.path_id,
        "path_label": guide.path_label,
        "snapshot_id": guide.snapshot_id,
        "policy_id": guide.policy_id,
        "analysis_start_timestamp": guide.analysis_start_timestamp,
        "as_of_timestamp": guide.as_of_timestamp,
        "build": {
            "archetype": guide.build_archetype,
            "tag_ids": list(guide.build_tag_ids),
            "tag_classes": list(guide.build_tag_classes),
            "tag_labels": list(guide.build_tag_labels),
            "tag_catalog_sha256": guide.build_tag_catalog_sha256,
        },
        "categories": [
            {
                "name": category.name,
                "optional": category.optional,
                "description": category.description,
                "width": category.width,
                "height": category.height,
                "items": [
                    {
                        "item_id": item.item_id,
                        "annotation": item.annotation,
                        "required_flex_slots": item.required_flex_slots,
                        "sell_priority": item.sell_priority,
                        "imbue_target_ability_id": item.imbue_target_ability_id,
                    }
                    for item in category.items
                ],
            }
            for category in guide.rendered_categories
        ],
    })
