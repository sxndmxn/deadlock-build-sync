from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

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
    TIER_CATEGORY_DESCRIPTION,
    GuideCategory,
    GuideItem,
    PurchaseGuide,
)
from .snapshot import sha256_json

MAX_ANNOTATION_BYTES = 240
_TRIGGER_TERMS = ("if ", "when ")
_CHOICE_TERMS = ("choose", "instead", "replace", " over ")
_EXECUTION_TERMS = ("use ", "activate", "before", "after", "hold ")
_FAILURE_TERMS = ("skip", "avoid", "unless", "fails", "do not")


def validate_optional_annotation(annotation: str) -> None:
    """Enforce bounded trigger/choice/execution/failure instructions.

    Raises:
        PolicyError: If a conditional tile cannot be executed from its annotation.

    """
    encoded = annotation.encode("utf-8")
    if not annotation.strip() or len(encoded) > MAX_ANNOTATION_BYTES:
        raise PolicyError(
            f"optional annotation must be 1–{MAX_ANNOTATION_BYTES} UTF-8 bytes"
        )
    normalized = annotation.casefold()
    requirements = (
        (_TRIGGER_TERMS, "trigger"),
        (_CHOICE_TERMS, "choice or replacement"),
        (_EXECUTION_TERMS, "execution"),
        (_FAILURE_TERMS, "failure condition"),
    )
    missing = [
        label
        for terms, label in requirements
        if not any(term in normalized for term in terms)
    ]
    if missing:
        raise PolicyError("optional annotation is missing: " + ", ".join(missing))


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


def _branch_label(branch: Branch) -> str:
    if not branch.guards:
        return "DEFAULT"
    values = [
        str(guard.value).replace("_", " ").upper()
        for guard in branch.guards
        if guard.value is not None
    ]
    label = "IF " + " + ".join(values or [branch.guards[0].field.upper()])
    return label[:48]


def _guide_item(
    node: PolicyNode,
    assets: dict[int, dict[str, Any]],
    policy: BuildPolicy,
    *,
    optional: bool,
) -> GuideItem:
    if node.item_id is None:
        raise PolicyError(f"purchase node {node.node_id} has no item")
    asset = assets.get(node.item_id)
    if asset is None:
        raise PolicyError(f"purchase node {node.node_id} references missing asset")
    claim = next(
        (claim for claim in policy.evidence if claim.claim_id == node.evidence_ref),
        None,
    )
    if claim is None:
        raise PolicyError(f"purchase node {node.node_id} has no current evidence")
    annotation = node.annotation.strip()
    if optional:
        validate_optional_annotation(annotation)
    elif not annotation:
        annotation = "Default core purchase; use the policy sidecar for timing and deviation rules."
    estimate = claim.estimate or 0.0
    interval_lower = claim.interval[0] if claim.interval is not None else 0.0
    return GuideItem(
        item_id=node.item_id,
        name=str(asset.get("name") or f"Item {node.item_id}"),
        tier=int(asset.get("item_tier") or 0),
        purchase_event_observations=claim.support,
        observed_outcome_rate=estimate,
        observed_outcome_lower_bound=interval_lower,
        relative_purchase_event_volume=0.0,
        windows=(),
        required_flex_slots=node.required_flex_slots or None,
        sell_priority=node.sell_priority,
        imbue_target_ability_id=node.imbue_target_ability_id,
        tactical_annotation=annotation,
    )


def _apply_sell_priorities(
    items: tuple[GuideItem, ...],
    path: tuple[PolicyNode, ...],
) -> tuple[GuideItem, ...]:
    priorities: dict[int, int] = {}
    for node in path:
        if node.kind == NodeKind.SELL and node.item_id is not None:
            priorities.setdefault(node.item_id, len(priorities) + 1)
    return tuple(
        replace(item, sell_priority=priorities.get(item.item_id, item.sell_priority))
        for item in items
    )


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


def _project_evidence_layout(
    policy: BuildPolicy,
    identity: ProjectionIdentity,
    layout: PurchaseGuide,
    default_path: tuple[PolicyNode, ...],
) -> PurchaseGuide:
    source_core_ids = tuple(item.item_id for item in layout.core_items)
    core_purchase_items = layout.core_purchase_items or layout.core_items
    core_purchase_ids = tuple(item.item_id for item in core_purchase_items)
    policy_core_ids = tuple(
        node.item_id
        for node in default_path
        if node.kind == NodeKind.PURCHASE and node.item_id is not None
    )
    if len(source_core_ids) != 8 or policy_core_ids != source_core_ids:
        raise PolicyError(
            "policy default path does not match the eight-item evidence core"
        )
    if any(not 1 <= len(layout.tiers.get(tier, ())) <= 10 for tier in range(1, 5)):
        raise PolicyError("evidence projection requires 1–10 items in every tier")
    tier_item_ids = {item.item_id for items in layout.tiers.values() for item in items}
    if tier_item_ids & set(core_purchase_ids):
        raise PolicyError("evidence tier menus must not repeat CORE path items")
    conditional = _conditional_nodes(policy)
    missing_conditional = set(conditional) - tier_item_ids
    if missing_conditional:
        raise PolicyError(
            "conditional policy items are missing from tier menus: "
            + ", ".join(str(item_id) for item_id in sorted(missing_conditional))
        )

    def project_item(item: GuideItem) -> GuideItem:
        node = conditional.get(item.item_id)
        if node is None:
            return item
        return replace(
            item,
            tactical_annotation=node.annotation,
            required_flex_slots=node.required_flex_slots or None,
            sell_priority=node.sell_priority,
            imbue_target_ability_id=node.imbue_target_ability_id,
        )

    tiers = {
        tier: tuple(project_item(item) for item in items)
        for tier, items in layout.tiers.items()
    }
    core_items = _apply_sell_priorities(layout.core_items, policy.nodes)
    core_purchase_items = _apply_sell_priorities(core_purchase_items, policy.nodes)
    categories = (
        GuideCategory(
            "CORE ITEMS",
            core_purchase_items,
            CORE_CATEGORY_DESCRIPTION,
        ),
        *(
            GuideCategory(
                f"TIER {tier}",
                tiers[tier],
                TIER_CATEGORY_DESCRIPTION,
                optional=True,
            )
            for tier in range(1, 5)
        ),
    )
    return PurchaseGuide(
        hero_id=policy.hero_id,
        hero_name=identity.hero_name,
        hero_class_name=identity.hero_class_name,
        tiers=tiers,
        summary=(
            f"{policy.strategic_role}; coherent eight-item core observed in "
            f"{layout.core_joint_matches:,} player-matches "
            f"({layout.core_joint_share * 100:.2f}%). Tier rows are "
            "adoption reference menus, not automatic purchases."
        ),
        categories=categories,
        snapshot_id=policy.snapshot_id,
        policy_id=policy.policy_id,
        client_version=identity.client_version,
        match_mode=identity.match_mode,
        rank_identity=identity.rank_identity,
        core_items=core_items,
        core_purchase_items=core_purchase_items,
        core_joint_matches=layout.core_joint_matches,
        core_joint_share=layout.core_joint_share,
        median_final_net_worth=layout.median_final_net_worth,
        core_target_cost=layout.core_target_cost,
    )


def project_policy_to_guide(
    policy: BuildPolicy,
    context: ValidationContext,
    *,
    assets: list[dict[str, Any]],
    identity: ProjectionIdentity,
    layout_source: PurchaseGuide | None = None,
) -> PurchaseGuide:
    """Validate a rich policy and create its compact executable Steam projection.

    Returns:
        A guide whose Queue contains only the default path and whose alternatives are optional.

    Raises:
        PolicyError: If any graph path or projected annotation is invalid.

    """
    validate_policy(policy, context)
    nodes = {node.node_id: node for node in policy.nodes}
    assets_by_id = {
        int(asset["id"]): asset for asset in assets if isinstance(asset.get("id"), int)
    }
    default_path = _linear_projection(nodes, policy.entry)
    if layout_source is not None:
        return _project_evidence_layout(policy, identity, layout_source, default_path)
    core_items = tuple(
        _guide_item(node, assets_by_id, policy, optional=False)
        for node in default_path
        if node.kind == NodeKind.PURCHASE
    )
    core_items = _apply_sell_priorities(core_items, policy.nodes)
    if not core_items:
        raise PolicyError("default policy path contains no purchase")
    categories: list[GuideCategory] = [
        GuideCategory(
            "CORE — DEFAULT QUEUE",
            core_items,
            "Minimal coherent default path. Recalculate when a conditional trigger applies.",
        )
    ]
    default_item_ids = {item.item_id for item in core_items}
    seen_optional: set[tuple[int, ...]] = set()
    for choice in policy.nodes:
        if choice.kind not in {NodeKind.CHOICE, NodeKind.OBJECTIVE_GATE}:
            continue
        for branch in choice.branches:
            if branch.is_default:
                continue
            path = _linear_projection(nodes, branch.next_id)
            items = tuple(
                _guide_item(node, assets_by_id, policy, optional=True)
                for node in path
                if node.kind == NodeKind.PURCHASE
                and node.item_id not in default_item_ids
            )
            items = _apply_sell_priorities(items, policy.nodes)
            item_identity = tuple(item.item_id for item in items)
            if not items or item_identity in seen_optional:
                continue
            seen_optional.add(item_identity)
            categories.append(
                GuideCategory(
                    _branch_label(branch),
                    items,
                    "Conditional branch; excluded from the default Queue.",
                    optional=True,
                )
            )
    tiers: dict[int, tuple[GuideItem, ...]] = {
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


def projection_fingerprint(guide: PurchaseGuide) -> str:
    """Fingerprint all behavior emitted into the compact projection.

    Returns:
        SHA-256 of item/category semantics and identity fields.

    """
    return sha256_json({
        "hero_id": guide.hero_id,
        "snapshot_id": guide.snapshot_id,
        "policy_id": guide.policy_id,
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
