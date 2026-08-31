from __future__ import annotations

from .artifacts import ArtifactError
from .build_evidence_types import (
    MINIMUM_TIER_SUPPORT,
    CorePolicyEvidence,
    ItemEvidence,
    SequencePolicy,
    SituationalPolicy,
    TierPolicyEvidence,
)


def validate_policy_item_references(
    core_policy: CorePolicyEvidence,
    tier_policy: TierPolicyEvidence,
    sequence_policy: SequencePolicy,
    situational_policy: SituationalPolicy,
    *,
    items: tuple[ItemEvidence, ...],
    hero_id: int,
) -> None:
    item_ids = {item.item_id for item in items}
    referenced_items = (
        set(core_policy.backbone_item_ids)
        | set(core_policy.default_item_ids)
        | {row.item_id for row in core_policy.alternatives}
        | {row.comparator_item_id for row in core_policy.alternatives}
        | {
            item_id
            for tier_item_ids in tier_policy.item_ids_by_tier.values()
            for item_id in tier_item_ids
        }
        | set(sequence_policy.default_path)
        | {row.next_item_id for row in sequence_policy.transitions}
        | {branch.item_id for branch in situational_policy.branches}
        | {branch.comparator_item_id for branch in situational_policy.branches}
    )
    if not referenced_items <= item_ids:
        raise ArtifactError(f"hero {hero_id} policy references missing item evidence")
    items_by_id = {item.item_id: item for item in items}
    if any(
        items_by_id[branch.item_id].adopter_matches < MINIMUM_TIER_SUPPORT
        for branch in situational_policy.branches
    ):
        raise ArtifactError(f"hero {hero_id} has a weak situational tier item")
    core_target_ids = set(core_policy.default_item_ids)
    if any(
        branch.comparator_item_id not in core_target_ids
        or items_by_id[branch.item_id].tier != branch.tier
        or items_by_id[branch.comparator_item_id].tier != branch.tier
        for branch in situational_policy.branches
    ):
        raise ArtifactError(f"hero {hero_id} has an invalid situational comparator")
