from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from deadlock_build_sync import policy_runtime
from deadlock_build_sync.mechanics import InventoryState, MechanicsError
from deadlock_build_sync.policy import (
    Abstention,
    AbstentionReason,
    Branch,
    BuildPolicy,
    ClaimClass,
    CoreAlternativeCard,
    CounterCard,
    EvaluationState,
    Guard,
    GuardOperator,
    NodeKind,
    PolicyDecision,
    PolicyError,
    PolicyNode,
    SpikeCard,
)
from tests.test_policy import SNAPSHOT_ID, branching_policy, context

if TYPE_CHECKING:
    from collections.abc import Callable


def _counter(item_id: int = 2, evidence_ref: str = "item/counter") -> CounterCard:
    return CounterCard(
        threat="control",
        item_id=item_id,
        comparator_item_id=1,
        mechanic_ref="asset:item:2",
        legal_timing="before fight",
        alternative="counter",
        replacement="replace core",
        execution_mode="reactive",
        failure_condition="skip otherwise",
        evidence_ref=evidence_ref,
        enemy_mechanics_refs=("asset:hero:3",),
    )


def _alternative(
    item_id: int = 2,
    comparator_item_id: int = 1,
    evidence_ref: str = "item/counter",
) -> CoreAlternativeCard:
    return CoreAlternativeCard(
        item_id=item_id,
        comparator_item_id=comparator_item_id,
        stage=1,
        vs="Spirit damage",
        why="Resist",
        swap="Replace core",
        when="Before fight",
        skip="Keep core otherwise",
        mechanics_refs=("asset:item:2",),
        comparator_mechanics_refs=("asset:item:1",),
        evidence_ref=evidence_ref,
        support=40,
        effective_support=30,
        overlap=0.8,
        interval=(0.01, 0.05),
        fold_estimates={"train": 0.03, "validation": 0.04},
    )


def test_guard_validation_covers_every_operator_contract() -> None:
    assert Guard("clock_s", GuardOperator.EXISTS).matches({"clock_s": 1})
    with pytest.raises(PolicyError, match="integer comparison"):
        Guard("cohort.match_mode", GuardOperator.AT_LEAST, 1)
    with pytest.raises(PolicyError, match="integer comparison"):
        Guard("clock_s", GuardOperator.AT_MOST, "1")
    with pytest.raises(PolicyError, match="not a collection"):
        Guard("clock_s", GuardOperator.CONTAINS, 1)
    with pytest.raises(PolicyError, match="incompatible value"):
        Guard("clock_s", GuardOperator.EQUALS, "1")


def test_guard_matches_all_comparisons_and_bad_state_types() -> None:
    assert Guard("clock_s", GuardOperator.EQUALS, 3).matches({"clock_s": 3})
    assert Guard("clock_s", GuardOperator.NOT_EQUALS, 3).matches({"clock_s": 4})
    assert Guard("clock_s", GuardOperator.AT_LEAST, 3).matches({"clock_s": 4})
    assert not Guard("clock_s", GuardOperator.AT_LEAST, 3).matches({"clock_s": "4"})
    assert Guard("clock_s", GuardOperator.AT_MOST, 3).matches({"clock_s": 2})
    assert not Guard("clock_s", GuardOperator.AT_MOST, 3).matches({"clock_s": None})
    assert Guard("enemy.items", GuardOperator.CONTAINS, 2).matches({"enemy.items": [2]})
    assert not Guard("enemy.items", GuardOperator.CONTAINS, 2).matches({
        "enemy.items": 2
    })


def test_branch_properties_cover_default_conjunction_and_matching() -> None:
    default = Branch("end")
    assert default.is_default
    assert default.guards == ()
    assert not default.matches({})

    first = Guard("level", GuardOperator.AT_LEAST, 1)
    second = Guard("level", GuardOperator.AT_MOST, 5)
    branch = Branch("end", first, additional_guards=(second,))
    assert branch.guards == (first, second)
    assert branch.matches({"level": 3})
    assert not branch.matches({"level": 6})


@pytest.mark.parametrize(
    "factory",
    [
        lambda: PolicyNode("", NodeKind.END),
        lambda: PolicyNode("buy", NodeKind.PURCHASE),
        lambda: PolicyNode("sell", NodeKind.SELL),
        lambda: PolicyNode("ability", NodeKind.ABILITY, ability_id=1),
        lambda: PolicyNode("choice", NodeKind.CHOICE),
        lambda: PolicyNode("end", NodeKind.END, branches=(Branch("end"),)),
        lambda: PolicyNode("end", NodeKind.END, next_id="other"),
        lambda: PolicyNode("wait", NodeKind.WAIT, required_flex_slots=4),
        lambda: PolicyNode("wait", NodeKind.WAIT, sell_priority=0),
        lambda: PolicyNode(
            "wait",
            NodeKind.WAIT,
            earliest_time_s=10,
            latest_time_s=9,
        ),
    ],
)
def test_policy_node_rejects_invalid_kind_specific_fields(
    factory: Callable[[], PolicyNode],
) -> None:
    with pytest.raises(PolicyError):
        factory()


def test_policy_node_successors_cover_branches_next_and_terminal() -> None:
    assert PolicyNode(
        "choice",
        NodeKind.CHOICE,
        branches=(Branch("one"), Branch("two")),
    ).successors() == ("one", "two")
    assert PolicyNode("wait", NodeKind.WAIT, next_id="end").successors() == ("end",)
    assert PolicyNode("end", NodeKind.END).successors() == ()


def test_abstention_and_policy_identity_validation_fail_closed() -> None:
    with pytest.raises(PolicyError, match="detail"):
        Abstention(AbstentionReason.ILLEGAL_PATH, " ")

    policy = branching_policy()
    mutations = (
        {"schema_version": 0},
        {"hero_id": 0},
        {"variant": ""},
        {"entry": "missing"},
    )
    for mutation in mutations:
        with pytest.raises(PolicyError):
            replace(policy, **mutation)


def test_policy_rejects_duplicate_nodes_claims_bad_ability_and_stale_claim() -> None:
    policy = branching_policy()
    with pytest.raises(PolicyError, match="node IDs"):
        replace(policy, nodes=(*policy.nodes, policy.nodes[0]))
    with pytest.raises(PolicyError, match="ability plan"):
        replace(policy, ability_plan=(PolicyNode("wait", NodeKind.WAIT),))
    with pytest.raises(PolicyError, match="evidence IDs"):
        replace(policy, evidence=(*policy.evidence, policy.evidence[0]))
    stale = replace(policy.evidence[0], snapshot_id="other")
    with pytest.raises(PolicyError, match="stale snapshot"):
        replace(policy, evidence=(stale, *policy.evidence[1:]))


def test_counter_card_policy_links_are_unique_and_exact() -> None:
    policy = branching_policy()
    card = _counter()
    with pytest.raises(PolicyError, match="distinct items"):
        replace(policy, counter_cards=(card, card))
    with pytest.raises(PolicyError, match="missing evidence"):
        replace(policy, counter_cards=(_counter(evidence_ref="missing"),))
    with pytest.raises(PolicyError, match="no matching optional"):
        replace(policy, counter_cards=(_counter(item_id=3),))
    assert replace(policy, counter_cards=(card,)).counter_cards == (card,)


def test_core_alternative_policy_links_and_schema_are_strict() -> None:
    policy = branching_policy()
    card = _alternative()
    with pytest.raises(PolicyError, match="distinct items"):
        replace(policy, schema_version=5, core_alternatives=(card, card))
    with pytest.raises(PolicyError, match="missing evidence"):
        replace(
            policy,
            schema_version=5,
            core_alternatives=(_alternative(evidence_ref="missing"),),
        )
    with pytest.raises(PolicyError, match="does not replace"):
        replace(
            policy,
            schema_version=5,
            core_alternatives=(_alternative(comparator_item_id=3),),
        )
    with pytest.raises(PolicyError, match="schema 1"):
        replace(policy, core_alternatives=(card,))


def test_spike_card_requires_confidence_and_transition_fields() -> None:
    card = SpikeCard(
        name="First core",
        prerequisites=("tier one",),
        acquisition_state="owned",
        mechanical_delta="more range",
        conversion_window="next fight",
        failure_conditions=("enemy disengages",),
        counterplay=("keep distance",),
        evidence_class=ClaimClass.MECHANICAL,
        confidence=0.8,
        evidence_ref="item/core",
    )

    assert card.name == "First core"
    with pytest.raises(PolicyError, match="confidence"):
        replace(card, confidence=1.1)
    with pytest.raises(PolicyError, match="state-transition"):
        replace(card, counterplay=())


def test_choice_validation_rejects_default_and_priority_errors() -> None:
    guarded = Guard("level", GuardOperator.AT_LEAST, 1)
    with pytest.raises(PolicyError, match="exactly one default"):
        policy_runtime._validate_choice(
            PolicyNode(
                "choice",
                NodeKind.CHOICE,
                branches=(Branch("one", guarded),),
            )
        )
    with pytest.raises(PolicyError, match="duplicate priorities"):
        policy_runtime._validate_choice(
            PolicyNode(
                "choice",
                NodeKind.CHOICE,
                branches=(
                    Branch("one", guarded, 1),
                    Branch("two", Guard("level", GuardOperator.AT_MOST, 5), 1),
                    Branch("end"),
                ),
            )
        )


def test_apply_nodes_cover_imbue_sell_priority_and_objective_unlock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validation_context = context()
    state = policy_runtime._PathState()
    calls: list[str] = []
    monkeypatch.setattr(
        policy_runtime,
        "validate_imbue",
        lambda *_args, **_kwargs: calls.append("imbue"),
    )
    node = PolicyNode(
        "buy",
        NodeKind.PURCHASE,
        item_id=1,
        imbue_target_ability_id=10,
        sell_priority=2,
    )
    purchased = policy_runtime._apply_purchase_node(node, state, validation_context)
    assert calls == ["imbue"]
    assert purchased.sell_priorities == ((1, 2),)

    objective = PolicyNode(
        "gate",
        NodeKind.OBJECTIVE_GATE,
        branches=(Branch("end"),),
        unlocks_flex_slots=2,
    )
    unlocked = policy_runtime._apply_node(objective, state, validation_context)
    assert unlocked.inventory.unlocked_flex_slots == 2


def test_apply_node_wraps_mechanics_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*_args: object, **_kwargs: object) -> InventoryState:
        raise MechanicsError("illegal")

    monkeypatch.setattr(policy_runtime, "purchase_item", fail)
    node = PolicyNode("buy", NodeKind.PURCHASE, item_id=1)
    with pytest.raises(PolicyError, match="node buy"):
        policy_runtime._apply_node(node, policy_runtime._PathState(), context())


def test_runtime_defensive_action_checks_reject_corrupt_nodes() -> None:
    buy = PolicyNode("buy", NodeKind.PURCHASE, item_id=1)
    sell = PolicyNode("sell", NodeKind.SELL, item_id=1)
    ability = PolicyNode("ability", NodeKind.ABILITY, ability_id=10, level=1)
    vars(buy)["item_id"] = None
    vars(sell)["item_id"] = None
    vars(ability)["level"] = None
    state = policy_runtime._PathState()
    with pytest.raises(PolicyError, match="has no item"):
        policy_runtime._apply_purchase_node(buy, state, context())
    with pytest.raises(PolicyError, match="has no item"):
        policy_runtime._apply_sell_node(sell, state, context())
    with pytest.raises(PolicyError, match="incomplete"):
        policy_runtime._apply_ability_node(ability, state, context())


def test_policy_node_validation_checks_evidence_and_optional_successors() -> None:
    node = PolicyNode("buy", NodeKind.PURCHASE, item_id=1, evidence_ref="missing")
    with pytest.raises(PolicyError, match="missing evidence"):
        policy_runtime._validate_policy_node(
            node,
            {"buy": node},
            {},
            validate_successors=False,
        )
    no_evidence = PolicyNode("buy", NodeKind.PURCHASE, item_id=1)
    with pytest.raises(PolicyError, match="has no evidence"):
        policy_runtime._validate_policy_node(
            no_evidence,
            {"buy": no_evidence},
            {},
            validate_successors=False,
        )


def test_graph_validation_rejects_cycle_nonterminal_and_unreachable() -> None:
    for nodes, message in (
        (
            (
                PolicyNode("one", NodeKind.WAIT, next_id="two"),
                PolicyNode("two", NodeKind.WAIT, next_id="one"),
            ),
            "reachable cycle",
        ),
        ((PolicyNode("one", NodeKind.WAIT),), "does not terminate"),
        (
            (
                PolicyNode("end", NodeKind.END),
                PolicyNode("other", NodeKind.END),
            ),
            "unreachable nodes",
        ),
    ):
        policy = BuildPolicy(
            5,
            12,
            "test",
            "kit",
            "role",
            SNAPSHOT_ID,
            nodes[0].node_id,
            nodes,
            (),
        )
        with pytest.raises(PolicyError, match=message):
            policy_runtime.validate_policy(policy, context())


def test_choice_step_handles_owned_ambiguous_prioritized_and_default_paths() -> None:
    one = PolicyNode("one", NodeKind.PURCHASE, item_id=1, optional=True)
    two = PolicyNode("two", NodeKind.PURCHASE, item_id=2, optional=True)
    end = PolicyNode("end", NodeKind.END)
    choice = PolicyNode(
        "choice",
        NodeKind.CHOICE,
        branches=(
            Branch("one", Guard("level", GuardOperator.AT_LEAST, 1)),
            Branch("two", Guard("level", GuardOperator.AT_MOST, 5)),
            Branch("end"),
        ),
    )
    nodes = {node.node_id: node for node in (choice, one, two, end)}
    ambiguous = policy_runtime._choice_step(
        choice,
        EvaluationState({"level": 3}, inventory=InventoryState((1, 2))),
        nodes,
    )
    assert isinstance(ambiguous, PolicyDecision)
    assert ambiguous.abstention is not None

    fulfilled = policy_runtime._choice_step(
        choice,
        EvaluationState({"level": 10}, inventory=InventoryState((1,))),
        nodes,
    )
    assert isinstance(fulfilled, PolicyDecision)
    assert fulfilled.kind == NodeKind.END

    runtime_ambiguous = policy_runtime._choice_step(
        choice,
        EvaluationState({"level": 3}),
        nodes,
    )
    assert isinstance(runtime_ambiguous, PolicyDecision)
    assert runtime_ambiguous.abstention is not None

    prioritized = replace(
        choice,
        branches=(
            Branch("one", Guard("level", GuardOperator.AT_LEAST, 1), 2),
            Branch("two", Guard("level", GuardOperator.AT_MOST, 5), 1),
            Branch("end"),
        ),
    )
    assert (
        policy_runtime._choice_step(
            prioritized,
            EvaluationState({"level": 3}),
            nodes,
        )
        == "two"
    )
    assert (
        policy_runtime._choice_step(
            choice,
            EvaluationState({}),
            nodes,
        )
        == "end"
    )


def test_node_evaluation_covers_fulfilled_and_missed_timing_paths() -> None:
    end_purchase = PolicyNode("buy", NodeKind.PURCHASE, item_id=1)
    state = EvaluationState({}, inventory=InventoryState((1,)))
    assert policy_runtime._node_is_fulfilled(end_purchase, state)
    assert not policy_runtime._node_is_fulfilled(
        PolicyNode("wait", NodeKind.WAIT), state
    )
    decision = policy_runtime._evaluate_policy_node(
        end_purchase,
        state,
        {"buy": end_purchase},
    )
    assert isinstance(decision, PolicyDecision)
    assert decision.kind == NodeKind.END

    timed = PolicyNode("wait", NodeKind.WAIT, latest_time_s=1)
    missed = policy_runtime._evaluate_policy_node(
        timed,
        EvaluationState({}, clock_s=2),
        {"wait": timed},
    )
    assert isinstance(missed, PolicyDecision)
    assert missed.abstention is not None
    recalculated = replace(timed, recalculation_next="end")
    assert (
        policy_runtime._evaluate_policy_node(
            recalculated,
            EvaluationState({}, clock_s=2),
            {"wait": recalculated},
        )
        == "end"
    )
