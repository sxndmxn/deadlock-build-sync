from dataclasses import replace

from deadlock_build_sync.build_evidence import (
    SequenceTransition,
)
from deadlock_build_sync.offline.config import sha256_json
from deadlock_build_sync.recommendation import (
    RecommendationAction,
    recommend,
)
from tests.recommendation_fixtures import (
    make_build_catalog,
    make_decision_state,
    make_expanded_assets,
    make_recommendation_assets,
    make_recommendation_policy,
)


def test_recommendation_expands_components_then_saves_for_parent() -> None:
    first = recommend(
        make_build_catalog(),
        make_recommendation_policy(),
        make_decision_state(),
        make_recommendation_assets(),
    )
    assert first.action is RecommendationAction.BUY
    assert first.item_id == 1
    assert first.target_item_id == 2
    assert first.incremental_cost == 500
    assert sha256_json(first.as_dict()) == (
        "8712d5362c1959c6d379d9ee1735d909b92b679fe0046ec0350eb5753749e25d"
    )

    second = recommend(
        make_build_catalog(),
        make_recommendation_policy(),
        make_decision_state(
            purchases=(1,),
            owned_items=(1,),
            owned_components=(1,),
            open_slots=8,
            liquid_souls=500,
        ),
        make_recommendation_assets(),
    )
    assert second.action is RecommendationAction.SAVE
    assert second.item_id == 2
    assert second.incremental_cost == 750


def test_manual_deviation_uses_supported_backoff() -> None:
    decision = recommend(
        make_build_catalog(),
        make_recommendation_policy(),
        make_decision_state(purchases=(99,), liquid_souls=2_000),
        make_recommendation_assets(),
    )

    assert decision.action is RecommendationAction.BUY
    assert decision.backoff_level == "policy"
    assert decision.support == 40


def test_sold_item_history_recalculates_from_actual_ownership() -> None:
    decision = recommend(
        make_build_catalog(),
        make_recommendation_policy(),
        make_decision_state(purchases=(3,), liquid_souls=500),
        make_recommendation_assets(),
    )

    assert decision.action is RecommendationAction.BUY
    assert decision.item_id == 1
    assert decision.target_item_id == 2


def test_full_slots_abstain_and_a_flex_unlock_restores_legality() -> None:
    full = make_decision_state(
        owned_items=tuple(range(3, 12)),
        open_slots=0,
        liquid_souls=500,
    )
    assert recommend(
        make_build_catalog(), make_recommendation_policy(), full, make_expanded_assets()
    ).action is (RecommendationAction.ABSTAIN)

    with_flex = replace(full, unlocked_flex_slots=1, open_slots=1)
    assert recommend(
        make_build_catalog(),
        make_recommendation_policy(),
        with_flex,
        make_expanded_assets(),
    ).action is (RecommendationAction.BUY)


def test_fifth_active_counter_is_rejected_before_default_recovery() -> None:
    decision = recommend(
        make_build_catalog(branch=True),
        make_recommendation_policy(branch=True),
        make_decision_state(
            threats=("healing",),
            owned_items=(4, 5, 6, 7),
            open_slots=5,
            active_bindings=4,
            liquid_souls=500,
        ),
        make_expanded_assets(active_ids=frozenset({3, 4, 5, 6, 7})),
    )

    assert decision.action is RecommendationAction.ABSTAIN
    assert "illegal" in decision.reason


def test_observational_sequence_transitions_do_not_control_runtime() -> None:
    base = make_build_catalog()
    hero = base.heroes[12]
    assert hero.sequence_policy is not None
    sparse_policy = replace(
        hero.sequence_policy,
        transitions=(SequenceTransition("position", 0, 0, 7, 2, 20, 20),),
    )
    sparse = replace(base, heroes={12: replace(hero, sequence_policy=sparse_policy)})

    decision = recommend(
        sparse,
        make_recommendation_policy(),
        make_decision_state(),
        make_recommendation_assets(),
    )

    assert decision.action is RecommendationAction.BUY
    assert decision.item_id == 1
    assert decision.backoff_level == "policy"


def test_owned_intermediate_upgrade_stops_prerequisite_recursion() -> None:
    item_assets: list[dict[str, object]] = [
        *make_recommendation_assets(),
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
    base_policy = make_recommendation_policy()
    core = next(node for node in base_policy.nodes if node.node_id == "core-1")
    nested_policy = replace(
        base_policy,
        nodes=tuple(
            replace(node, item_id=4) if node == core else node
            for node in base_policy.nodes
        ),
    )

    decision = recommend(
        make_build_catalog(),
        nested_policy,
        make_decision_state(
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
        make_build_catalog(branch=True),
        make_recommendation_policy(branch=True),
        make_decision_state(
            threats=("healing",),
            purchases=(1, 2),
            owned_items=(2,),
            open_slots=8,
            liquid_souls=2_000,
        ),
        make_recommendation_assets(),
    )

    assert decision.action is RecommendationAction.END


def test_owned_counter_persists_the_opportunity_replacement() -> None:
    decision = recommend(
        make_build_catalog(branch=True),
        make_recommendation_policy(branch=True),
        make_decision_state(
            purchases=(3,),
            owned_items=(3,),
            open_slots=8,
            liquid_souls=2_000,
        ),
        make_recommendation_assets(),
    )

    assert decision.action is RecommendationAction.END
