import json
from dataclasses import replace
from pathlib import Path

import pytest

from deadlock_build_sync.policy import (
    Branch,
    Guard,
    GuardOperator,
    NodeKind,
)
from deadlock_build_sync.recommendation import (
    DecisionState,
    RecommendationAction,
    RecommendationError,
    recommend,
)
from tests.recommendation_fixtures import (
    assets,
    build_policy,
    catalog,
    expanded_assets,
    state,
)


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
        json.dumps({"schema_version": 2, "build_evidence_id": "a" * 64}),
        encoding="utf-8",
    )

    with pytest.raises(RecommendationError, match="inventory"):
        DecisionState.from_file(path)

    path.write_text(
        json.dumps({
            "schema_version": 2,
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
            "schema_version": 2,
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
            "lane_enemy_hero_ids": [7],
            "enemy_item_ids": [4],
            "allied_hero_ids": [8],
            "objectives": ["mid boss"],
            "threats": [],
        }),
        encoding="utf-8",
    )

    decision_state = DecisionState.from_file(path)

    assert decision_state.enemy_item_ids == (4,)
    assert decision_state.lane_enemy_hero_ids == (7,)


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
