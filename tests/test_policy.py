from dataclasses import replace
from typing import Any

import pytest

from deadlock_build_sync.mechanics import (
    AbilityDefinition,
    InventoryState,
    ItemGraph,
)
from deadlock_build_sync.policy import (
    Branch,
    BuildPolicy,
    ClaimClass,
    CounterCard,
    EvaluationState,
    EvidenceClaim,
    Guard,
    GuardOperator,
    NodeKind,
    PolicyError,
    PolicyNode,
    SpikeCard,
    ValidationContext,
    next_policy_decision,
    validate_policy,
)
from deadlock_build_sync.snapshot import EvidenceUnit

SNAPSHOT_ID = "a" * 64


def assets(count: int = 10, *, active: bool = False) -> list[dict[str, Any]]:
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


def claim(
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


def context(item_assets: list[dict[str, Any]] | None = None) -> ValidationContext:
    return ValidationContext(
        ItemGraph.from_assets(item_assets or assets()),
        {10: AbilityDefinition(10, unlock_level=1)},
        {"1": {"bonus_currencies": ["EAbilityUnlocks"]}},
    )


def branching_policy() -> BuildPolicy:
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
            claim("mechanic/ability", ClaimClass.MECHANICAL),
            claim("item/counter"),
            claim("item/core"),
        ),
    )


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
    with pytest.raises(PolicyError, match="ability plan"):
        validate_policy(invalid, context())


def test_policy_rejects_unknown_kind_and_edited_fingerprint() -> None:
    payload = branching_policy().as_dict()
    payload["nodes"][0]["kind"] = "teleport"
    with pytest.raises(PolicyError, match="malformed policy node"):
        BuildPolicy.from_dict(payload)

    payload = branching_policy().as_dict()
    payload["variant"] = "edited"
    with pytest.raises(PolicyError, match="fingerprint"):
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
    invalid = BuildPolicy(
        policy.schema_version,
        policy.hero_id,
        policy.variant,
        policy.invariant_kit_id,
        policy.strategic_role,
        policy.snapshot_id,
        policy.entry,
        tuple(changed),
        policy.evidence,
    )
    with pytest.raises(PolicyError, match="missing successor"):
        validate_policy(invalid, context())


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
    invalid = BuildPolicy(
        policy.schema_version,
        policy.hero_id,
        policy.variant,
        policy.invariant_kit_id,
        policy.strategic_role,
        policy.snapshot_id,
        policy.entry,
        nodes,
        policy.evidence,
    )

    with pytest.raises(PolicyError, match="overlapping guards"):
        validate_policy(invalid, context())


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

    with pytest.raises(PolicyError, match="exceeds 9 available item slots"):
        validate_policy(policy, context())


def test_recalculation_skips_owned_and_handles_missed_timing() -> None:
    policy = branching_policy()
    state = EvaluationState(
        {"enemy.threats": []},
        inventory=InventoryState((1,)),
        learned_abilities=frozenset({10}),
    )
    assert next_policy_decision(policy, state).kind == NodeKind.END

    nodes = tuple(
        PolicyNode(
            node.node_id,
            node.kind,
            next_id=node.next_id,
            evidence_ref=node.evidence_ref,
            item_id=node.item_id,
            ability_id=node.ability_id,
            level=node.level,
            branches=node.branches,
            optional=node.optional,
            latest_time_s=100 if node.node_id == "core" else None,
            recalculation_next="end" if node.node_id == "core" else None,
        )
        for node in policy.nodes
    )
    missed = BuildPolicy(
        policy.schema_version,
        policy.hero_id,
        policy.variant,
        policy.invariant_kit_id,
        policy.strategic_role,
        policy.snapshot_id,
        policy.entry,
        nodes,
        policy.evidence,
    )
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
