from dataclasses import replace

from deadlock_build_sync import artifact_bundle
from deadlock_build_sync.policy import (
    Branch,
    Guard,
    GuardOperator,
    NodeKind,
    PolicyNode,
)
from tests.artifact_bundle_fixtures import (
    _policy,
)


def test_policy_core_follows_default_through_situational_choice() -> None:
    policy = _policy("snapshot")
    choice = PolicyNode(
        "choice",
        NodeKind.CHOICE,
        branches=(
            Branch(
                "situational",
                Guard("enemy.threats", GuardOperator.CONTAINS, "healing"),
            ),
            Branch("core-1"),
        ),
    )
    situational = PolicyNode(
        "situational",
        NodeKind.PURCHASE,
        next_id="end",
        item_id=999,
        optional=True,
    )
    branched = replace(
        policy,
        entry="choice",
        nodes=(choice, situational, *policy.nodes),
    )

    assert artifact_bundle._policy_core(branched) == tuple(range(1001, 1007))
