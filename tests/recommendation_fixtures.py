from dataclasses import replace

from deadlock_build_sync.build_evidence import (
    BuildEvidenceCatalog,
    CorePolicyEvidence,
    HeroBuildEvidence,
    SequencePolicy,
    SequenceTransition,
    SituationalBranch,
    SituationalPolicy,
    TierPolicyEvidence,
)
from deadlock_build_sync.policy import (
    Branch,
    BuildPolicy,
    ClaimClass,
    CounterCard,
    EvidenceClaim,
    Guard,
    GuardOperator,
    NodeKind,
    PolicyNode,
)
from deadlock_build_sync.recommendation import (
    DecisionState,
)
from deadlock_build_sync.snapshot import EpochBoundary, EpochSet, EvidenceUnit


def assets() -> list[dict[str, object]]:
    return [
        {
            "id": 1,
            "class_name": "component",
            "name": "Component",
            "cost": 500,
            "item_tier": 1,
            "item_slot_type": "weapon",
            "shopable": True,
            "disabled": False,
            "component_items": [],
        },
        {
            "id": 2,
            "class_name": "parent",
            "name": "Parent",
            "cost": 1_250,
            "item_tier": 2,
            "item_slot_type": "weapon",
            "shopable": True,
            "disabled": False,
            "component_items": ["component"],
        },
        {
            "id": 3,
            "class_name": "anti_heal",
            "name": "Anti-Heal",
            "cost": 1_000,
            "item_tier": 2,
            "item_slot_type": "spirit",
            "shopable": True,
            "disabled": False,
            "component_items": [],
        },
    ]


def expanded_assets(
    *, active_ids: frozenset[int] = frozenset()
) -> list[dict[str, object]]:
    rows = assets()
    for row in rows:
        row["is_active_item"] = row["id"] in active_ids
    rows.extend(
        {
            "id": item_id,
            "class_name": f"item_{item_id}",
            "name": f"Item {item_id}",
            "cost": 500,
            "item_tier": 1,
            "item_slot_type": "vitality",
            "shopable": True,
            "disabled": False,
            "component_items": [],
            "is_active_item": item_id in active_ids,
        }
        for item_id in range(4, 12)
    )
    return rows


def catalog(*, branch: bool = False) -> BuildEvidenceCatalog:
    boundary = EpochBoundary("patch", 1)
    situational = SituationalPolicy(
        (
            SituationalBranch(
                threat="healing",
                item_id=3,
                enemy_hero_id=None,
                mechanic_ref="item/3/healing-reduction",
                comparator="default continuation or save",
                comparator_item_id=2,
                comparison_support=30,
                same_opportunity=True,
                support=30,
                effective_support=25.0,
                overlap=0.8,
                stable=True,
                comparative_interval=(0.01, 0.06),
                trigger="Enemy healing is observed.",
                replacement="Replace the next optional purchase.",
                execution="Apply the supplied healing reduction after contact.",
                failure_condition="Skip when healing is not material.",
            ),
        )
        if branch
        else (),
        ("unsupported branches abstain",),
    )
    hero = HeroBuildEvidence(
        hero_id=12,
        hero="Kelvin",
        eligible_player_matches=100,
        selection_eligible_player_matches=80,
        fold_eligible_player_matches={"train": 40, "validation": 40, "test": 20},
        median_final_net_worth=20_000,
        items=(),
        core_policy=CorePolicyEvidence(
            (1, 2, 4, 5),
            (1, 2, 4, 5, 6, 7, 8, 9),
            60,
            {"train": 20, "validation": 20, "test": 20},
            30,
            (),
            (),
            {"method": "cross-fitted-dr"},
        ),
        tier_policy=TierPolicyEvidence({}),
        sequence_policy=SequencePolicy(
            (1, 2),
            (SequenceTransition("popularity", 0, 0, 0, 2, 40, 100),),
            20,
            "deterministic_backoff",
            {"fold": "test"},
        ),
        situational_policy=situational,
    )
    return BuildEvidenceCatalog(
        "a" * 64,
        123,
        {"identity": "b" * 64},
        {
            "as_of": "2026-01-01T00:00:00+00:00",
            "match_mode": "Ranked",
            "game_mode": "Normal",
            "minimum_badge": 71,
            "maximum_badge": 115,
        },
        EpochSet(boundary, boundary, boundary, boundary),
        "c" * 64,
        "d" * 64,
        "e" * 64,
        frozenset({12}),
        {12: hero},
        b"fixture",
    )


def build_policy(*, branch: bool = False) -> BuildPolicy:
    snapshot_id = "e" * 64
    core_claim = EvidenceClaim(
        "hero/12/core",
        ClaimClass.DESCRIPTIVE,
        snapshot_id,
        {"match_mode": "ranked"},
        EvidenceUnit.ELIGIBLE_APPEARANCE,
        100,
        ("item/2",),
        frozenset({"observed", "adopted", "rate"}),
        numerator=40,
        denominator=100,
        estimate=0.4,
    )
    evidence = [core_claim]
    nodes: list[PolicyNode] = []
    cards: tuple[CounterCard, ...] = ()
    entry = "core-1"
    if branch:
        counter_claim = EvidenceClaim(
            "hero/12/healing/3",
            ClaimClass.DESCRIPTIVE,
            snapshot_id,
            {"match_mode": "ranked"},
            EvidenceUnit.HERO_ENEMY_PAIR,
            30,
            ("item/3/healing-reduction",),
            frozenset({"observed", "associated"}),
            estimate=0.03,
            interval=(0.01, 0.06),
            comparison_baseline=0.0,
        )
        evidence.append(counter_claim)
        entry = "situational-choice-1"
        nodes.extend((
            PolicyNode(
                entry,
                NodeKind.CHOICE,
                branches=(
                    Branch(
                        "situational-1",
                        Guard(
                            "enemy.threats",
                            GuardOperator.CONTAINS,
                            "healing",
                        ),
                    ),
                    Branch("core-1"),
                ),
            ),
            PolicyNode(
                "situational-1",
                NodeKind.PURCHASE,
                next_id="end",
                evidence_ref=counter_claim.claim_id,
                item_id=3,
                optional=True,
                annotation="Enemy healing is observed.",
            ),
        ))
        cards = (
            CounterCard(
                "healing",
                3,
                2,
                "item/3/healing-reduction",
                "same observed decision opportunity",
                "default continuation or save",
                "Replace the next optional purchase.",
                "Apply the supplied healing reduction after contact.",
                "Skip when healing is not material.",
                counter_claim.claim_id,
                enemy_mechanics_refs=("asset:ability:7:description",),
            ),
        )
    nodes.extend((
        PolicyNode(
            "core-1",
            NodeKind.PURCHASE,
            next_id="end",
            evidence_ref=core_claim.claim_id,
            item_id=2,
        ),
        PolicyNode("end", NodeKind.END),
    ))
    return BuildPolicy(
        1,
        12,
        "core",
        "kit/12",
        "test",
        snapshot_id,
        entry,
        tuple(nodes),
        tuple(evidence),
        counter_cards=cards,
    )


def state(**changes: object) -> DecisionState:
    base = DecisionState(
        build_evidence_id="a" * 64,
        client_version=123,
        patch_identity="b" * 64,
        match_mode="Ranked",
        game_mode="Normal",
        hero_id=12,
        clock_s=300,
        average_badge=90,
        liquid_souls=500,
        purchases=(),
        owned_items=(),
        owned_components=(),
        open_slots=9,
        unlocked_flex_slots=0,
        active_bindings=0,
        learned_abilities=(),
    )
    return replace(base, **changes)
