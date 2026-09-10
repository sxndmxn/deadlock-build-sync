"""Fresh policy objects for policy and codec tests."""

from __future__ import annotations

from deadlock_build_sync.mechanics import (
    AbilityDefinition,
    ItemGraph,
)
from deadlock_build_sync.policy import (
    Branch,
    BuildPolicy,
    ClaimClass,
    EvidenceClaim,
    Guard,
    GuardOperator,
    NodeKind,
    PolicyNode,
    ValidationContext,
)
from deadlock_build_sync.snapshot import EvidenceUnit

SNAPSHOT_ID = "a" * 64


def make_policy_assets(
    count: int = 10, *, active: bool = False
) -> list[dict[str, object]]:
    return [
        {
            "id": item_id,
            "class_name": f"item_{item_id}",
            "name": f"Item {item_id}",
            "cost": 500,
            "component_items": [],
            "item_slot_type": "weapon",
            "item_tier": 1,
            "shopable": True,
            "disabled": False,
            "is_active_item": active,
        }
        for item_id in range(1, count + 1)
    ]


def make_evidence_claim(
    claim_id: str,
    claim_class: ClaimClass = ClaimClass.DESCRIPTIVE,
) -> EvidenceClaim:
    return EvidenceClaim(
        claim_id=claim_id,
        claim_class=claim_class,
        snapshot_id=SNAPSHOT_ID,
        cohort={"match_mode": "ranked", "rank_badges": [91, 116]},
        unit=(
            EvidenceUnit.ASSET
            if claim_class == ClaimClass.MECHANICAL
            else EvidenceUnit.ELIGIBLE_APPEARANCE
        ),
        support=100,
        mechanics_refs=("asset/10",),
        language_ceiling=frozenset(
            {"grants"} if claim_class == ClaimClass.MECHANICAL else {"observed"}
        ),
        numerator=60 if claim_class != ClaimClass.MECHANICAL else None,
        denominator=100 if claim_class != ClaimClass.MECHANICAL else None,
        estimate=0.6 if claim_class != ClaimClass.MECHANICAL else None,
        interval=(0.5, 0.69) if claim_class != ClaimClass.MECHANICAL else None,
        comparison_baseline=0.5 if claim_class != ClaimClass.MECHANICAL else None,
    )


def make_validation_context(
    item_assets: list[dict[str, object]] | None = None,
) -> ValidationContext:
    return ValidationContext(
        ItemGraph.from_assets(item_assets or make_policy_assets()),
        {10: AbilityDefinition(10, unlock_level=1)},
        {"1": {"bonus_currencies": ["EAbilityUnlocks"]}},
    )


def make_branching_policy() -> BuildPolicy:
    return BuildPolicy(
        schema_version=1,
        hero_id=12,
        variant="control-utility",
        invariant_kit_id="kit/12",
        strategic_role="space control",
        snapshot_id=SNAPSHOT_ID,
        entry="unlock",
        nodes=(
            PolicyNode(
                "unlock",
                NodeKind.ABILITY,
                next_id="counter_check",
                evidence_ref="mechanic/ability",
                ability_id=10,
                level=1,
            ),
            PolicyNode(
                "counter_check",
                NodeKind.CHOICE,
                branches=(
                    Branch(
                        "counter",
                        Guard(
                            "enemy.threats",
                            GuardOperator.CONTAINS,
                            "hard_control",
                        ),
                    ),
                    Branch("core"),
                ),
            ),
            PolicyNode(
                "counter",
                NodeKind.PURCHASE,
                next_id="end",
                evidence_ref="item/counter",
                item_id=2,
                optional=True,
                annotation="If hard control is observed, choose this over core; activate before commitment; skip if the threat is absent.",
            ),
            PolicyNode(
                "core",
                NodeKind.PURCHASE,
                next_id="end",
                evidence_ref="item/core",
                item_id=1,
            ),
            PolicyNode("end", NodeKind.END),
        ),
        evidence=(
            make_evidence_claim("mechanic/ability", ClaimClass.MECHANICAL),
            make_evidence_claim("item/counter"),
            make_evidence_claim("item/core"),
        ),
    )
