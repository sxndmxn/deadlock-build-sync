from __future__ import annotations

from typing import TYPE_CHECKING

from .mechanics import (
    AbilityDefinition,
    conditional_item_decision,
)
from .policy import (
    ClaimClass,
    CoreAlternativeCard,
    EvidenceClaim,
)
from .purchase_guide import (
    PurchaseGuide,
    conditional_item_annotation,
)
from .snapshot import EvidenceUnit

if TYPE_CHECKING:
    from .build_evidence import (
        CoreAlternativeEvidence,
        SituationalBranch,
    )
    from .purchase_guide import GuideItem
    from .snapshot import SnapshotManifest

from .service_types import GuideError, _cohort


def _mechanical_claim(
    *,
    claim_id: str,
    mechanics_ref: str,
    manifest: SnapshotManifest,
) -> EvidenceClaim:
    return EvidenceClaim(
        claim_id=claim_id,
        claim_class=ClaimClass.MECHANICAL,
        snapshot_id=manifest.snapshot_id,
        cohort=_cohort(manifest),
        unit=EvidenceUnit.ASSET,
        support=1,
        mechanics_refs=(mechanics_ref,),
        language_ceiling=frozenset({"grants", "requires", "can target"}),
    )


def _item_claim(
    item: GuideItem,
    *,
    manifest: SnapshotManifest,
) -> EvidenceClaim:
    return EvidenceClaim(
        claim_id=f"item/{item.item_id}/adoption",
        claim_class=ClaimClass.DESCRIPTIVE,
        snapshot_id=manifest.snapshot_id,
        cohort=_cohort(manifest),
        unit=EvidenceUnit.ELIGIBLE_APPEARANCE,
        support=item.eligible_player_matches,
        mechanics_refs=(f"item/{item.item_id}",),
        language_ceiling=frozenset({"observed", "adopted", "rate", "more common"}),
        numerator=item.adopter_matches,
        denominator=item.eligible_player_matches,
        estimate=item.purchase_adoption,
        comparison_baseline=None,
    )


def _core_claim(guide: PurchaseGuide, manifest: SnapshotManifest) -> EvidenceClaim:
    return EvidenceClaim(
        claim_id=f"hero/{guide.hero_id}/stable-supported-backbone",
        claim_class=ClaimClass.DESCRIPTIVE,
        snapshot_id=manifest.snapshot_id,
        cohort=_cohort(manifest),
        unit=EvidenceUnit.ELIGIBLE_APPEARANCE,
        support=guide.core_items[0].eligible_player_matches,
        mechanics_refs=tuple(f"item/{item.item_id}" for item in guide.backbone_items),
        language_ceiling=frozenset({"observed", "adopted", "rate", "more common"}),
        numerator=guide.backbone_matches,
        denominator=guide.core_items[0].eligible_player_matches,
        estimate=guide.backbone_share,
    )


def _core_alternative_claim(
    guide: PurchaseGuide,
    alternative: CoreAlternativeEvidence,
    manifest: SnapshotManifest,
) -> EvidenceClaim:
    return EvidenceClaim(
        claim_id=(
            f"hero/{guide.hero_id}/core-alternative/"
            f"{alternative.item_id}-for-{alternative.comparator_item_id}"
        ),
        claim_class=ClaimClass.PREDICTIVE,
        snapshot_id=manifest.snapshot_id,
        cohort=_cohort(manifest),
        unit=EvidenceUnit.PURCHASE_EVENT,
        support=alternative.support + alternative.comparison_support,
        mechanics_refs=(
            *alternative.mechanics_refs,
            *alternative.comparator_mechanics_refs,
        ),
        language_ceiling=frozenset({"estimated", "conditional", "expected"}),
        estimate=alternative.dr_estimate,
        interval=alternative.comparative_interval,
        comparison_baseline=0.0,
    )


def _core_alternative_cards(
    guide: PurchaseGuide,
    manifest: SnapshotManifest,
) -> tuple[tuple[CoreAlternativeCard, ...], tuple[EvidenceClaim, ...]]:
    claims = tuple(
        _core_alternative_claim(guide, alternative, manifest)
        for alternative in guide.core_alternatives
    )
    cards = tuple(
        CoreAlternativeCard(
            item_id=alternative.item_id,
            comparator_item_id=alternative.comparator_item_id,
            stage=alternative.stage,
            vs=alternative.vs,
            why=alternative.why,
            swap=alternative.swap,
            when=alternative.when,
            skip=alternative.skip,
            mechanics_refs=alternative.mechanics_refs,
            comparator_mechanics_refs=alternative.comparator_mechanics_refs,
            evidence_ref=claim.claim_id,
            support=alternative.support + alternative.comparison_support,
            effective_support=alternative.effective_support,
            overlap=alternative.overlap,
            interval=alternative.comparative_interval,
            fold_estimates=alternative.fold_estimates,
        )
        for alternative, claim in zip(guide.core_alternatives, claims, strict=True)
    )
    return cards, claims


def _situational_claim(
    branch: SituationalBranch,
    *,
    hero_id: int,
    manifest: SnapshotManifest,
) -> EvidenceClaim:
    enemy = branch.enemy_hero_id if branch.enemy_hero_id is not None else "any"
    return EvidenceClaim(
        claim_id=(
            f"hero/{hero_id}/situational/{branch.threat}/{enemy}/{branch.item_id}"
        ),
        claim_class=ClaimClass.DESCRIPTIVE,
        snapshot_id=manifest.snapshot_id,
        cohort=_cohort(manifest),
        unit=EvidenceUnit.HERO_ENEMY_PAIR,
        support=branch.support,
        mechanics_refs=(branch.mechanic_ref,),
        language_ceiling=frozenset({"observed", "associated"}),
        estimate=sum(branch.comparative_interval) / 2,
        interval=branch.comparative_interval,
        comparison_baseline=0.0,
    )


def _situational_annotation(
    branch: SituationalBranch,
    *,
    assets_by_id: dict[int, dict[str, object]],
) -> str:
    item_asset = assets_by_id[branch.item_id]
    comparator_asset = assets_by_id[branch.comparator_item_id]
    comparator = str(
        comparator_asset.get("name") or f"item {branch.comparator_item_id}"
    )
    response = branch.mechanic_ref.rsplit("/", 1)[-1]
    decision = conditional_item_decision(
        item_asset,
        comparator_asset,
        response=response,
    )
    if decision is None:
        raise GuideError(
            f"situational item {branch.item_id} has no concrete decision copy"
        )
    vs, why, when, skip = decision
    try:
        return conditional_item_annotation(
            vs=vs,
            why=why,
            swap=f"Replaces {comparator}",
            when=when,
            skip=skip,
        )
    except ValueError as error:
        raise GuideError(
            f"situational annotation for item {branch.item_id} is invalid"
        ) from error


def _policy_evidence(
    guide: PurchaseGuide,
    definitions: dict[int, AbilityDefinition],
    manifest: SnapshotManifest,
) -> tuple[dict[str, EvidenceClaim], EvidenceClaim]:
    item_claims = {
        item.item_id: _item_claim(item, manifest=manifest)
        for item in (
            *(item for tier_items in guide.tiers.values() for item in tier_items),
            *guide.optional_core_items,
        )
    }
    evidence = {claim.claim_id: claim for claim in item_claims.values()}
    core_claim = _core_claim(guide, manifest)
    evidence[core_claim.claim_id] = core_claim
    for ability_id in definitions:
        claim = _mechanical_claim(
            claim_id=f"ability/{ability_id}/mechanics",
            mechanics_ref=f"ability/{ability_id}",
            manifest=manifest,
        )
        evidence[claim.claim_id] = claim
    return evidence, core_claim
