import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from deadlock_build_sync.build_evidence import (
    BuildEvidenceCatalog,
    HeroBuildEvidence,
    SequencePolicy,
    SequenceTransition,
    SituationalBranch,
    SituationalPolicy,
)
from deadlock_build_sync.recommendation import (
    DecisionState,
    RecommendationAction,
    RecommendationError,
    recommend,
)
from deadlock_build_sync.snapshot import EpochBoundary, EpochSet


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
                support=30,
                effective_support=25.0,
                overlap=0.8,
                stable=True,
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
        SequencePolicy(
            (1, 2),
            (SequenceTransition("popularity", 0, 0, 0, 2, 40, 100),),
            20,
            "deterministic_backoff",
            {"fold": "test"},
            {"passed": False, "promoted": False},
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
    first = recommend(catalog(), state(), assets())
    assert first.action is RecommendationAction.BUY
    assert first.item_id == 1
    assert first.target_item_id == 2
    assert first.incremental_cost == 500

    second = recommend(
        catalog(),
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
        state(purchases=(99,), liquid_souls=2_000),
        assets(),
    )

    assert decision.action is RecommendationAction.BUY
    assert decision.backoff_level == "popularity"
    assert decision.support == 40


def test_sold_item_history_recalculates_from_actual_ownership() -> None:
    decision = recommend(
        catalog(),
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
    assert recommend(catalog(), full, expanded_assets()).action is (
        RecommendationAction.ABSTAIN
    )

    with_flex = replace(full, unlocked_flex_slots=1, open_slots=1)
    assert recommend(catalog(), with_flex, expanded_assets()).action is (
        RecommendationAction.BUY
    )


def test_fifth_active_counter_is_rejected_before_default_recovery() -> None:
    decision = recommend(
        catalog(branch=True),
        state(
            threats=("healing",),
            owned_items=(4, 5, 6, 7),
            open_slots=5,
            active_bindings=4,
            liquid_souls=500,
        ),
        expanded_assets(active_ids=frozenset({3, 4, 5, 6, 7})),
    )

    assert decision.action is RecommendationAction.BUY
    assert decision.item_id == 1
    assert decision.backoff_level == "popularity"


def test_sparse_transition_state_abstains() -> None:
    base = catalog()
    hero = base.heroes[12]
    assert hero.sequence_policy is not None
    sparse_policy = replace(
        hero.sequence_policy,
        transitions=(SequenceTransition("position", 0, 0, 7, 2, 20, 20),),
    )
    sparse = replace(base, heroes={12: replace(hero, sequence_policy=sparse_policy)})

    decision = recommend(sparse, state(), assets())

    assert decision.action is RecommendationAction.ABSTAIN
    assert "no supported legal next action" in decision.reason


def test_repeated_component_path_ends_only_after_the_rebuy() -> None:
    base = catalog()
    hero = base.heroes[12]
    assert hero.sequence_policy is not None
    policy = replace(
        hero.sequence_policy,
        default_path=(1, 2, 1),
        transitions=(SequenceTransition("position", 0, 0, 9, 2, 20, 20),),
    )
    repeated = replace(base, heroes={12: replace(hero, sequence_policy=policy)})

    incomplete = recommend(
        repeated,
        state(
            purchases=(1, 2),
            owned_items=(2,),
            open_slots=8,
        ),
        assets(),
    )
    assert incomplete.action is RecommendationAction.ABSTAIN

    complete = recommend(
        repeated,
        state(
            purchases=(1, 2, 1),
            owned_items=(1, 2),
            owned_components=(1,),
            open_slots=7,
        ),
        assets(),
    )
    assert complete.action is RecommendationAction.END


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
    with pytest.raises(RecommendationError, match=message):
        recommend(catalog(), state(**change), assets())


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


def test_situational_branch_and_unknown_threat_are_explicit() -> None:
    decision = recommend(
        catalog(branch=True),
        state(threats=("healing",), liquid_souls=1_000),
        assets(),
    )
    assert decision.action is RecommendationAction.BUY
    assert decision.item_id == 3
    assert decision.counter is not None
    assert decision.counter["failure_condition"] == "Skip when healing is not material."

    unknown = recommend(
        catalog(branch=True),
        state(threats=("magic_vibes",)),
        assets(),
    )
    assert unknown.action is RecommendationAction.ABSTAIN
    assert "unknown threat" in unknown.reason
