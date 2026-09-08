from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from deadlock_build_sync.mechanics import (
    InventoryState,
)
from deadlock_build_sync.policy import (
    Branch,
    BuildPolicy,
    ClaimClass,
    CoreAlternativeCard,
    CounterCard,
    EvaluationState,
    Guard,
    GuardOperator,
    NodeKind,
    PolicyError,
    PolicyNode,
    SpikeCard,
    next_policy_decision,
    validate_policy,
)
from deadlock_build_sync.value_validation import require_object_rows
from tests.policy_fixtures import SNAPSHOT_ID, branching_policy, claim, context

if TYPE_CHECKING:
    from collections.abc import Callable


def test_core_alternative_accepts_the_ninth_universal_slot() -> None:
    card = CoreAlternativeCard(
        item_id=1,
        comparator_item_id=2,
        stage=9,
        vs="Heavy Spirit damage",
        why="Spirit Resist",
        swap="Replaces Item 2",
        when="Before a Spirit-heavy fight",
        skip="Keep default when catch matters more",
        mechanics_refs=("asset:item:1",),
        comparator_mechanics_refs=("asset:item:2",),
        evidence_ref="alternative/1",
        support=40,
        effective_support=30,
        overlap=0.8,
        interval=(0.01, 0.05),
        fold_estimates={"train": 0.03, "validation": 0.04, "test": 0.0},
    )

    assert card.stage == 9


def test_policy_round_trips_all_typed_nodes_and_fingerprint() -> None:
    policy = branching_policy()

    decoded = BuildPolicy.from_dict(policy.as_dict())

    assert decoded == policy
    assert decoded.policy_id == policy.policy_id
    assert {node.kind for node in decoded.nodes} >= {
        NodeKind.PURCHASE,
        NodeKind.CHOICE,
        NodeKind.ABILITY,
        NodeKind.END,
    }
    for kind in (NodeKind.SELL, NodeKind.WAIT, NodeKind.OBJECTIVE_GATE):
        node = PolicyNode(
            f"node-{kind.value}",
            kind,
            next_id=None if kind == NodeKind.END else "end",
            item_id=1 if kind == NodeKind.SELL else None,
            evidence_ref="item/core" if kind == NodeKind.SELL else None,
            branches=(Branch("end"),) if kind == NodeKind.OBJECTIVE_GATE else (),
        )
        assert PolicyNode.from_dict(node.as_dict()) == node


def test_policy_validates_ability_plan_separately_from_runtime_graph() -> None:
    policy = BuildPolicy(
        schema_version=1,
        hero_id=12,
        variant="separate-clocks",
        invariant_kit_id="kit/12",
        strategic_role="space control",
        snapshot_id=SNAPSHOT_ID,
        entry="end",
        nodes=(PolicyNode("end", NodeKind.END),),
        evidence=(claim("mechanic/ability", ClaimClass.MECHANICAL),),
        ability_plan=(
            PolicyNode(
                "ability-1",
                NodeKind.ABILITY,
                evidence_ref="mechanic/ability",
                ability_id=10,
                level=1,
            ),
        ),
    )

    validate_policy(policy, context())
    assert BuildPolicy.from_dict(policy.as_dict()).ability_plan == policy.ability_plan
    assert policy.entry == "end"

    invalid = replace(
        policy,
        ability_plan=(
            *policy.ability_plan,
            PolicyNode(
                "ability-2",
                NodeKind.ABILITY,
                evidence_ref="mechanic/ability",
                ability_id=10,
                level=1,
            ),
        ),
    )
    validation_context = context()
    with pytest.raises(PolicyError, match="ability plan"):
        validate_policy(invalid, validation_context)


def test_policy_rejects_unknown_kind_and_edited_fingerprint() -> None:
    payload = branching_policy().as_dict()
    nodes = require_object_rows(payload["nodes"])
    nodes[0]["kind"] = "teleport"
    with pytest.raises(PolicyError, match="malformed policy node"):
        BuildPolicy.from_dict(payload)

    payload = branching_policy().as_dict()
    payload["variant"] = "edited"
    with pytest.raises(PolicyError, match="fingerprint"):
        BuildPolicy.from_dict(payload)


@pytest.mark.parametrize(
    ("mutation", "error"),
    [
        (lambda payload: payload.update(unexpected=True), "malformed build policy"),
        (
            lambda payload: payload["nodes"][0].update(unexpected=True),
            "malformed policy node",
        ),
        (lambda payload: payload.update(hero_id="12"), "malformed build policy"),
        (
            lambda payload: payload["nodes"][0].update(optional=1),
            "malformed policy node",
        ),
    ],
)
def test_policy_codec_rejects_extra_fields_and_primitive_coercion(
    mutation: Callable[[dict[str, object]], None],
    error: str,
) -> None:
    payload = branching_policy().as_dict()
    mutation(payload)

    with pytest.raises(PolicyError, match=error):
        BuildPolicy.from_dict(payload)


def test_validate_policy_checks_every_branch_and_terminates() -> None:
    policy = branching_policy()

    validate_policy(policy, context())

    changed = list(policy.nodes)
    changed[2] = PolicyNode(
        "counter",
        NodeKind.PURCHASE,
        next_id="missing",
        evidence_ref="item/counter",
        item_id=2,
        optional=True,
    )
    invalid = replace(policy, nodes=tuple(changed))
    validation_context = context()
    with pytest.raises(PolicyError, match="missing successor"):
        validate_policy(invalid, validation_context)


def test_choice_requires_default_and_rejects_ambiguous_overlap() -> None:
    duplicate_guard = Guard("level", GuardOperator.AT_LEAST, 5)
    choice = PolicyNode(
        "counter_check",
        NodeKind.CHOICE,
        branches=(
            Branch("counter", duplicate_guard),
            Branch("core", duplicate_guard),
            Branch("core"),
        ),
    )
    policy = branching_policy()
    nodes = tuple(
        choice if node.node_id == "counter_check" else node for node in policy.nodes
    )
    invalid = replace(policy, nodes=nodes)
    validation_context = context()

    with pytest.raises(PolicyError, match="overlapping guards"):
        validate_policy(invalid, validation_context)


def test_all_path_validation_finds_slot_error_hidden_in_one_branch() -> None:
    nodes = [
        PolicyNode(
            f"buy-{item_id}",
            NodeKind.PURCHASE,
            next_id=f"buy-{item_id + 1}" if item_id < 9 else "choice",
            evidence_ref="item/core",
            item_id=item_id,
        )
        for item_id in range(1, 10)
    ]
    nodes.extend((
        PolicyNode(
            "choice",
            NodeKind.CHOICE,
            branches=(
                Branch(
                    "overflow",
                    Guard("enemy.threats", GuardOperator.CONTAINS, "burst"),
                ),
                Branch("end"),
            ),
        ),
        PolicyNode(
            "overflow",
            NodeKind.PURCHASE,
            next_id="end",
            evidence_ref="item/core",
            item_id=10,
        ),
        PolicyNode("end", NodeKind.END),
    ))
    policy = BuildPolicy(
        1,
        12,
        "weapon",
        "kit/12",
        "damage",
        SNAPSHOT_ID,
        "buy-1",
        tuple(nodes),
        (claim("item/core"),),
    )
    validation_context = context()

    with pytest.raises(PolicyError, match="exceeds 9 available item slots"):
        validate_policy(policy, validation_context)


def test_recalculation_skips_owned_and_handles_missed_timing() -> None:
    policy = branching_policy()
    state = EvaluationState(
        {"enemy.threats": []},
        inventory=InventoryState((1,)),
        learned_abilities=frozenset({10}),
    )
    assert next_policy_decision(policy, state).kind == NodeKind.END

    nodes = tuple(
        replace(
            node,
            latest_time_s=100 if node.node_id == "core" else None,
            recalculation_next="end" if node.node_id == "core" else None,
        )
        for node in policy.nodes
    )
    missed = replace(policy, nodes=nodes)
    decision = next_policy_decision(
        missed,
        EvaluationState(
            {"enemy.threats": []},
            learned_abilities=frozenset({10}),
            clock_s=101,
        ),
    )
    assert decision.kind == NodeKind.END


def test_claim_language_counter_and_spike_contracts_fail_closed() -> None:
    descriptive = claim("item/core")
    descriptive.validate_sentence("This item was observed more often in this cohort.")
    with pytest.raises(PolicyError, match="exceeds descriptive"):
        descriptive.validate_sentence("This item improves win rate.")
    with pytest.raises(PolicyError, match="counter card"):
        CounterCard(
            "hard control",
            2,
            1,
            "",
            "now",
            "save",
            "sell one",
            "reactive",
            "none",
            "claim",
        )
    with pytest.raises(PolicyError, match="outcome-only"):
        SpikeCard(
            "Peak",
            ("item",),
            "owned",
            "",
            "contest",
            ("behind",),
            ("dispel",),
            ClaimClass.DESCRIPTIVE,
            0.5,
            "item/core",
        )


def test_guards_reject_future_or_unknown_state() -> None:
    with pytest.raises(PolicyError, match="unknown observable"):
        Guard("future.final_net_worth", GuardOperator.AT_LEAST, 10_000)


@pytest.mark.parametrize("relative_state", ["ahead", "even", "behind"])
def test_relative_economy_guard_is_observable(relative_state: str) -> None:
    guard = Guard(
        "economy.relative_state",
        GuardOperator.EQUALS,
        relative_state,
    )

    assert guard.matches({"economy.relative_state": relative_state})
