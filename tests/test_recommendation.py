import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from deadlock_build_sync.build_evidence import (
    BuildEvidenceCatalog,
    CorePolicyEvidence,
    HeroBuildEvidence,
    SequencePolicy,
    SequenceTransition,
    SituationalBranch,
    SituationalPolicy,
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
    RecommendationAction,
    RecommendationError,
    recommend,
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
        12,
        "Kelvin",
        100,
        20_000,
        (),
        (),
        CorePolicyEvidence(
            (1, 2, 4, 5),
            (1, 2, 4, 5, 6, 7, 8, 9),
            60,
            {"train": 20, "validation": 20, "test": 20},
            30,
            (),
            (),
            {"method": "cross-fitted-dr"},
        ),
        SequencePolicy(
            (1, 2),
            (SequenceTransition("popularity", 0, 0, 0, 2, 40, 100),),
            20,
            "deterministic_backoff",
            {"fold": "test"},
        ),
        situational,
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


def state(**changes: Any) -> DecisionState:
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


def test_recommendation_expands_components_then_saves_for_parent() -> None:
    first = recommend(catalog(), build_policy(), state(), assets())
    assert first.action is RecommendationAction.BUY
    assert first.item_id == 1
    assert first.target_item_id == 2
    assert first.incremental_cost == 500

    second = recommend(
        catalog(),
        build_policy(),
        state(
            purchases=(1,),
            owned_items=(1,),
            owned_components=(1,),
            open_slots=8,
            liquid_souls=500,
        ),
        assets(),
    )
    assert second.action is RecommendationAction.SAVE
    assert second.item_id == 2
    assert second.incremental_cost == 750


def test_manual_deviation_uses_supported_backoff() -> None:
    decision = recommend(
        catalog(),
        build_policy(),
        state(purchases=(99,), liquid_souls=2_000),
        assets(),
    )

    assert decision.action is RecommendationAction.BUY
    assert decision.backoff_level == "policy"
    assert decision.support == 40


def test_sold_item_history_recalculates_from_actual_ownership() -> None:
    decision = recommend(
        catalog(),
        build_policy(),
        state(purchases=(3,), liquid_souls=500),
        assets(),
    )

    assert decision.action is RecommendationAction.BUY
    assert decision.item_id == 1
    assert decision.target_item_id == 2


def test_full_slots_abstain_and_a_flex_unlock_restores_legality() -> None:
    full = state(
        owned_items=tuple(range(3, 12)),
        open_slots=0,
        liquid_souls=500,
    )
    assert recommend(catalog(), build_policy(), full, expanded_assets()).action is (
        RecommendationAction.ABSTAIN
    )

    with_flex = replace(full, unlocked_flex_slots=1, open_slots=1)
    assert recommend(
        catalog(), build_policy(), with_flex, expanded_assets()
    ).action is (RecommendationAction.BUY)


def test_fifth_active_counter_is_rejected_before_default_recovery() -> None:
    decision = recommend(
        catalog(branch=True),
        build_policy(branch=True),
        state(
            threats=("healing",),
            owned_items=(4, 5, 6, 7),
            open_slots=5,
            active_bindings=4,
            liquid_souls=500,
        ),
        expanded_assets(active_ids=frozenset({3, 4, 5, 6, 7})),
    )

    assert decision.action is RecommendationAction.ABSTAIN
    assert "illegal" in decision.reason


def test_observational_sequence_transitions_do_not_control_runtime() -> None:
    base = catalog()
    hero = base.heroes[12]
    assert hero.sequence_policy is not None
    sparse_policy = replace(
        hero.sequence_policy,
        transitions=(SequenceTransition("position", 0, 0, 7, 2, 20, 20),),
    )
    sparse = replace(base, heroes={12: replace(hero, sequence_policy=sparse_policy)})

    decision = recommend(sparse, build_policy(), state(), assets())

    assert decision.action is RecommendationAction.BUY
    assert decision.item_id == 1
    assert decision.backoff_level == "policy"


def test_owned_intermediate_upgrade_stops_prerequisite_recursion() -> None:
    item_assets = [
        *assets(),
        {
            "id": 4,
            "class_name": "final",
            "name": "Final",
            "cost": 3_000,
            "item_tier": 3,
            "item_slot_type": "weapon",
            "shopable": True,
            "disabled": False,
            "component_items": ["parent"],
        },
    ]
    base_policy = build_policy()
    core = next(node for node in base_policy.nodes if node.node_id == "core-1")
    nested_policy = replace(
        base_policy,
        nodes=tuple(
            replace(node, item_id=4) if node == core else node
            for node in base_policy.nodes
        ),
    )

    decision = recommend(
        catalog(),
        nested_policy,
        state(
            purchases=(1, 2),
            owned_items=(2,),
            owned_components=(2,),
            open_slots=8,
            liquid_souls=2_000,
        ),
        item_assets,
    )

    assert decision.action is RecommendationAction.BUY
    assert decision.item_id == 4
    assert decision.incremental_cost == 1_750


def test_complete_core_ends_before_optional_threat_branch() -> None:
    decision = recommend(
        catalog(branch=True),
        build_policy(branch=True),
        state(
            threats=("healing",),
            purchases=(1, 2),
            owned_items=(2,),
            open_slots=8,
            liquid_souls=2_000,
        ),
        assets(),
    )

    assert decision.action is RecommendationAction.END


def test_owned_counter_persists_the_opportunity_replacement() -> None:
    decision = recommend(
        catalog(branch=True),
        build_policy(branch=True),
        state(
            purchases=(3,),
            owned_items=(3,),
            open_slots=8,
            liquid_souls=2_000,
        ),
        assets(),
    )

    assert decision.action is RecommendationAction.END


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"build_evidence_id": "f" * 64}, "another build-evidence"),
        ({"client_version": 124}, "another client"),
        ({"patch_identity": "f" * 64}, "another patch"),
        ({"match_mode": "Unranked"}, "matchmaking mode"),
        ({"average_badge": 70}, "outside the evidence cohort"),
    ],
)
def test_stale_or_out_of_cohort_state_fails_closed(
    change: dict[str, object],
    message: str,
) -> None:
    evidence = catalog()
    decision_state = state(**change)
    item_assets = assets()
    policy = build_policy()
    with pytest.raises(RecommendationError, match=message):
        recommend(evidence, policy, decision_state, item_assets)


def test_decision_state_file_requires_complete_context(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    path.write_text(
        json.dumps({"schema_version": 1, "build_evidence_id": "a" * 64}),
        encoding="utf-8",
    )

    with pytest.raises(RecommendationError, match="inventory"):
        DecisionState.from_file(path)

    path.write_text(
        json.dumps({
            "schema_version": 1,
            "account_id": 123,
            "build_evidence_id": "a" * 64,
        }),
        encoding="utf-8",
    )
    with pytest.raises(RecommendationError, match="unsupported fields: account_id"):
        DecisionState.from_file(path)


def test_decision_state_file_admits_deidentified_enemy_items(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    path.write_text(
        json.dumps({
            "schema_version": 1,
            "build_evidence_id": "a" * 64,
            "client_version": 123,
            "patch_identity": "b" * 64,
            "match_mode": "Ranked",
            "game_mode": "Normal",
            "hero_id": 12,
            "clock_s": 300,
            "average_badge": 90,
            "liquid_souls": 500,
            "purchases": [],
            "inventory": {
                "items": [],
                "components": [],
                "open_slots": 9,
                "flex_slots": 0,
                "active_bindings": 0,
            },
            "learned_abilities": [],
            "enemy_hero_ids": [7],
            "enemy_item_ids": [4],
            "allied_hero_ids": [8],
            "objectives": ["mid boss"],
            "threats": [],
        }),
        encoding="utf-8",
    )

    decision_state = DecisionState.from_file(path)

    assert decision_state.enemy_item_ids == (4,)


def test_situational_branch_and_unknown_threat_are_explicit() -> None:
    decision = recommend(
        catalog(branch=True),
        build_policy(branch=True),
        state(threats=("healing",), liquid_souls=1_000),
        assets(),
    )
    assert decision.action is RecommendationAction.BUY
    assert decision.item_id == 3
    assert decision.counter is not None
    assert decision.counter["failure_condition"] == "Skip when healing is not material."

    save = recommend(
        catalog(branch=True),
        build_policy(branch=True),
        state(threats=("healing",), liquid_souls=999),
        assets(),
    )
    assert save.action is RecommendationAction.SAVE
    assert save.target_item_id == 3

    unknown = recommend(
        catalog(branch=True),
        build_policy(branch=True),
        state(threats=("magic_vibes",)),
        assets(),
    )
    assert unknown.action is RecommendationAction.ABSTAIN
    assert "unknown threat" in unknown.reason


def test_conflicting_situational_branches_fail_closed() -> None:
    base_policy = build_policy(branch=True)
    choice = next(node for node in base_policy.nodes if node.kind == NodeKind.CHOICE)
    first = choice.branches[0]
    conflicting_policy = replace(
        base_policy,
        nodes=tuple(
            replace(
                node,
                branches=(
                    first,
                    Branch(
                        first.next_id,
                        Guard(
                            "enemy.threats",
                            GuardOperator.CONTAINS,
                            "control",
                        ),
                    ),
                    choice.branches[-1],
                ),
            )
            if node == choice
            else node
            for node in base_policy.nodes
        ),
    )
    decision_state = state(threats=("healing", "control"))
    item_assets = expanded_assets()

    decision = recommend(
        catalog(branch=True),
        conflicting_policy,
        decision_state,
        item_assets,
    )

    assert decision.action is RecommendationAction.ABSTAIN
    assert "multiple policy guards" in decision.reason


def test_enemy_item_mechanics_supply_an_observable_threat() -> None:
    item_assets = expanded_assets()
    next(row for row in item_assets if row["id"] == 4)["description"] = {
        "desc": "Restore Health to an ally."
    }

    decision = recommend(
        catalog(branch=True),
        build_policy(branch=True),
        state(enemy_item_ids=(4,), liquid_souls=1_000),
        item_assets,
    )

    assert decision.action is RecommendationAction.BUY
    assert decision.item_id == 3
    assert decision.backoff_level == "situational"


def test_full_active_bindings_supply_the_active_burden_threat() -> None:
    base_policy = build_policy(branch=True)
    choice = next(node for node in base_policy.nodes if node.kind == NodeKind.CHOICE)
    burden_policy = replace(
        base_policy,
        nodes=tuple(
            replace(
                node,
                branches=(
                    Branch(
                        choice.branches[0].next_id,
                        Guard(
                            "enemy.threats",
                            GuardOperator.CONTAINS,
                            "active_slot_burden",
                        ),
                    ),
                    choice.branches[-1],
                ),
            )
            if node == choice
            else node
            for node in base_policy.nodes
        ),
    )

    decision = recommend(
        catalog(branch=True),
        burden_policy,
        state(
            owned_items=(4, 5, 6, 7),
            open_slots=5,
            active_bindings=4,
            liquid_souls=1_000,
        ),
        expanded_assets(active_ids=frozenset({4, 5, 6, 7})),
    )

    assert decision.action is RecommendationAction.BUY
    assert decision.item_id == 3


def test_unknown_enemy_item_fails_closed() -> None:
    evidence = catalog(branch=True)
    decision_state = state(enemy_item_ids=(999,))
    item_assets = expanded_assets()
    policy = build_policy(branch=True)
    with pytest.raises(RecommendationError, match="unknown current item 999"):
        recommend(evidence, policy, decision_state, item_assets)
