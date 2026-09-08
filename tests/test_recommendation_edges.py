import json
from dataclasses import replace
from pathlib import Path

import pytest

from deadlock_build_sync import recommendation, recommendation_state
from deadlock_build_sync.hero_cohort import HeroCohort
from deadlock_build_sync.mechanics import InventoryState, ItemGraph
from deadlock_build_sync.policy import NodeKind, PolicyDecision, PolicyNode
from deadlock_build_sync.recommendation import (
    DecisionState,
    RecommendationAction,
    RecommendationError,
    recommend,
)
from deadlock_build_sync.value_validation import require_object_dict
from tests.discovery_fixtures import hero_cohort
from tests.recommendation_fixtures import (
    assets,
    build_policy,
    catalog,
    decision_state_document,
    expanded_assets,
    state,
)


def test_recommendation_uses_effective_hero_rank_range() -> None:
    evidence = catalog()
    hero = replace(evidence.heroes[12], cohort=HeroCohort.parse(hero_cohort()))
    expanded = replace(evidence, heroes={12: hero})
    for badge in (61, 71, 115):
        recommendation._validate_evidence_identity(expanded, state(average_badge=badge))
    for badge in (60, 116):
        with pytest.raises(RecommendationError, match="outside the evidence cohort"):
            recommendation._validate_evidence_identity(
                expanded, state(average_badge=badge)
            )
    with pytest.raises(RecommendationError, match="outside the evidence cohort"):
        recommendation._validate_evidence_identity(evidence, state(average_badge=61))


def _validate_scalar(function: str, value: object) -> None:
    if function == "integer":
        recommendation_state._integer(value, "value")
    elif function == "text":
        recommendation_state._text(value, "value")
    elif function == "integers":
        recommendation_state._integers(value, "value")
    elif function == "unique_integers":
        recommendation_state._unique_integers(value, "value")
    else:
        recommendation_state._unique_strings(value, "value")


def test_decision_state_loader_wraps_read_json_and_root_errors(tmp_path: Path) -> None:
    missing = tmp_path / "missing.json"
    with pytest.raises(RecommendationError, match="could not read decision state"):
        DecisionState.from_file(missing)

    path = tmp_path / "state.json"
    path.write_text("{", encoding="utf-8")
    with pytest.raises(RecommendationError, match="could not read decision state"):
        DecisionState.from_file(path)

    path.write_text("[]", encoding="utf-8")
    with pytest.raises(RecommendationError, match="root must be an object"):
        DecisionState.from_file(path)


def test_decision_state_loader_rejects_schema_and_inventory_extensions(
    tmp_path: Path,
) -> None:
    path = tmp_path / "state.json"
    document = decision_state_document()
    document["schema_version"] = 1
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(RecommendationError, match="unsupported decision-state schema"):
        DecisionState.from_file(path)

    document = decision_state_document()
    inventory = require_object_dict(document["inventory"])
    inventory["account_id"] = 7
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(RecommendationError, match="inventory contains unsupported"):
        DecisionState.from_file(path)


def test_decision_state_loader_requires_lane_membership(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    missing = decision_state_document()
    missing.pop("lane_enemy_hero_ids")
    path.write_text(json.dumps(missing), encoding="utf-8")
    with pytest.raises(RecommendationError, match="lacks lane enemy heroes"):
        DecisionState.from_file(path)

    outside = decision_state_document()
    outside["lane_enemy_hero_ids"] = [8]
    path.write_text(json.dumps(outside), encoding="utf-8")
    with pytest.raises(RecommendationError, match="not on the enemy team"):
        DecisionState.from_file(path)


@pytest.mark.parametrize(
    ("function", "value"),
    [
        ("integer", True),
        ("integer", 0),
        ("text", 7),
        ("text", " "),
        ("integers", {}),
        ("unique_integers", [1, 1]),
        ("unique_strings", ["ok", 7]),
        ("unique_strings", ["same", "same"]),
    ],
)
def test_decision_state_scalar_helpers_reject_bad_values(
    function: str,
    value: object,
) -> None:
    with pytest.raises(RecommendationError):
        _validate_scalar(function, value)


def test_recommendation_validates_game_mode_and_inventory_shape() -> None:
    with pytest.raises(RecommendationError, match="another game mode"):
        recommend(catalog(), build_policy(), state(game_mode="Other"), assets())
    with pytest.raises(RecommendationError, match="repeats an owned item"):
        recommend(
            catalog(),
            build_policy(),
            state(owned_items=(1, 1), open_slots=7),
            assets(),
        )
    with pytest.raises(RecommendationError, match="open-slot count"):
        recommend(catalog(), build_policy(), state(open_slots=8), assets())
    with pytest.raises(RecommendationError, match="active bindings"):
        recommend(catalog(), build_policy(), state(active_bindings=1), assets())
    with pytest.raises(RecommendationError, match="component ownership"):
        recommend(
            catalog(),
            build_policy(),
            state(owned_items=(1,), open_slots=8),
            assets(),
        )


def test_recommendation_wraps_mechanics_construction_error() -> None:
    with pytest.raises(RecommendationError, match="item graph is empty"):
        recommend(catalog(), build_policy(), state(), [])


def test_next_purchase_returns_none_for_an_owned_target() -> None:
    graph = ItemGraph.from_assets(assets())

    assert recommendation._next_purchase(1, InventoryState((1,)), graph) is None


def test_counter_metadata_must_be_unambiguous() -> None:
    policy = build_policy(branch=True)
    card = policy.counter_cards[0]
    object.__setattr__(  # ruff: ignore[unnecessary-dunder-call] - Fault injection bypasses frozen validation.
        policy, "counter_cards", (card, card)
    )

    with pytest.raises(RecommendationError, match="ambiguous counter metadata"):
        recommend(
            catalog(branch=True),
            policy,
            state(threats=("healing",), liquid_souls=1_000),
            assets(),
        )


def test_policy_node_recommendation_handles_nonpurchase_and_unclaimed_nodes() -> None:
    policy = build_policy()
    decision_state = state(liquid_souls=1_000)
    graph = ItemGraph.from_assets(assets())
    inventory = InventoryState()
    end = next(node for node in policy.nodes if node.kind == NodeKind.END)

    abstention = recommendation._recommend_policy_node(
        policy, decision_state, end, inventory, graph
    )
    assert abstention.action is RecommendationAction.ABSTAIN

    unclaimed = PolicyNode(
        "unclaimed",
        NodeKind.PURCHASE,
        item_id=1,
        evidence_ref="missing",
    )
    result = recommendation._recommend_policy_node(
        policy, decision_state, unclaimed, inventory, graph
    )
    assert result.support is None


def test_recommendation_checks_hero_coverage_and_policy_identity() -> None:
    evidence = catalog()
    with pytest.raises(RecommendationError, match="absent from build evidence"):
        recommend(replace(evidence, heroes={}), build_policy(), state(), assets())
    with pytest.raises(RecommendationError, match="differs from the build policy"):
        recommend(evidence, replace(build_policy(), hero_id=13), state(), assets())


def test_recommendation_abstains_for_an_empty_typed_decision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        recommendation,
        "next_policy_decision",
        lambda _policy, _state: PolicyDecision(None, None),
    )

    result = recommend(catalog(), build_policy(), state(), expanded_assets())

    assert result.action is RecommendationAction.ABSTAIN
    assert "no executable action" in result.reason
