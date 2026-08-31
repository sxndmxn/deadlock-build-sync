from __future__ import annotations

from .policy import Branch, BuildPolicy, NodeKind, PolicyError, PolicyNode
from .purchase_guide import GuideItem
from .renderer_validation import validate_optional_annotation
from .value_validation import integer


def branch_label(branch: Branch) -> str:
    if not branch.guards:
        return "DEFAULT"
    values = [
        str(guard.value).replace("_", " ").upper()
        for guard in branch.guards
        if guard.value is not None
    ]
    label = "IF " + " + ".join(values or [branch.guards[0].field.upper()])
    return label[:48]


def guide_item(
    node: PolicyNode,
    assets: dict[int, dict[str, object]],
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
        tier=integer(asset.get("item_tier"), default=0),
        purchase_event_observations=claim.support,
        observed_outcome_rate=estimate,
        observed_outcome_lower_bound=interval_lower,
        relative_purchase_event_volume=0.0,
        windows=(),
        required_flex_slots=node.required_flex_slots or None,
        sell_priority=node.sell_priority,
        imbue_target_ability_id=node.imbue_target_ability_id,
        tactical_annotation=annotation,
        conditional_annotation=annotation if optional else "",
    )


def project_guide_item_policy_fields(
    item: GuideItem,
    *,
    required_flex_slots: int | None,
    sell_priority: int | None,
    imbue_target_ability_id: int | None,
    conditional_annotation: str | None = None,
) -> GuideItem:
    return GuideItem(
        item_id=item.item_id,
        name=item.name,
        tier=item.tier,
        purchase_event_observations=item.purchase_event_observations,
        observed_outcome_rate=item.observed_outcome_rate,
        observed_outcome_lower_bound=item.observed_outcome_lower_bound,
        relative_purchase_event_volume=item.relative_purchase_event_volume,
        windows=item.windows,
        required_flex_slots=required_flex_slots,
        sell_priority=sell_priority,
        imbue_target_ability_id=imbue_target_ability_id,
        tactical_annotation=item.tactical_annotation,
        conditional_annotation=(
            item.conditional_annotation
            if conditional_annotation is None
            else conditional_annotation
        ),
        verified_tier_annotation=item.verified_tier_annotation,
        eligible_player_matches=item.eligible_player_matches,
        adopter_matches=item.adopter_matches,
        purchase_adoption=item.purchase_adoption,
        purchase_events=item.purchase_events,
        median_buy_time_s=item.median_buy_time_s,
        median_valid_buy_net_worth=item.median_valid_buy_net_worth,
        buy_net_worth_q25=item.buy_net_worth_q25,
        buy_net_worth_q75=item.buy_net_worth_q75,
        valid_buy_net_worth_share=item.valid_buy_net_worth_share,
        imbue_target_ability=item.imbue_target_ability,
        imbue_target_matches=item.imbue_target_matches,
        imbue_observations=item.imbue_observations,
        imbue_target_share=item.imbue_target_share,
    )


def apply_sell_priorities(
    items: tuple[GuideItem, ...],
    path: tuple[PolicyNode, ...],
) -> tuple[GuideItem, ...]:
    priorities: dict[int, int] = {}
    for node in path:
        if node.kind == NodeKind.SELL and node.item_id is not None:
            priorities.setdefault(node.item_id, len(priorities) + 1)
    return tuple(
        project_guide_item_policy_fields(
            item,
            required_flex_slots=item.required_flex_slots,
            sell_priority=priorities.get(item.item_id, item.sell_priority),
            imbue_target_ability_id=item.imbue_target_ability_id,
        )
        for item in items
    )
