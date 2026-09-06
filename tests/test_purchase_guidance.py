from dataclasses import replace

import pytest

from deadlock_build_sync.mechanics import ItemGraph, MechanicsError
from deadlock_build_sync.purchase_guidance import attach_purchase_guidance
from deadlock_build_sync.purchase_guidance_types import PurchaseState, PurchaseTiming
from deadlock_build_sync.purchase_markdown import build_markdown
from deadlock_build_sync.purchase_planner import plan_purchases
from deadlock_build_sync.purchase_purposes import purpose
from tests.mechanics_fixtures import item
from tests.purchase_guidance_fixtures import guidance_assets, guidance_fixture


def test_guidance_groups_all_options_and_retains_the_pool() -> None:
    guide, _ = guidance_fixture()
    guidance = guide.purchase_guidance
    assert guidance is not None
    assert [step.item_id for step in guidance.default_path.actions] == [1, 3, 2, 4, 5]
    assert {card.item_id for card in guidance.choices} == {6, 7, 8, 9, 10, 11, 12}
    defense = next(row for row in guidance.decisions if row.purpose == "Bullet defense")
    assert defense.kind == "PICK ONE"
    assert defense.options == (7, 8)
    fork = next(row for row in guidance.decisions if row.upgrade_fork)
    assert fork.options == (11, 12)
    trophy = next(card for card in guidance.choices if card.item_id == 6)
    assert trophy.extra_path_cost == 3200
    assert trophy.rebought_components == (1,)
    text = build_markdown(guide, details=True)
    assert "UPGRADE Sprint → Trophy" in text
    assert "Includes another Sprint" in text
    assert "You can stop at Range (+800 total)" in text
    assert "Mystery** — Timing unknown" in text
    assert text.index("PICK ONE — Bullet defense") < text.index("**3. Speed")
    assert (
        "Tier 1:** Trophy, Bullet Guard, Bullet Shield, Mystery, Range, Greater Range, Other Range"
        in text
    )


def test_purchase_recovery_keeps_lineages_and_rebuys_shared_components() -> None:
    _, graph = guidance_fixture()
    result = plan_purchases(
        graph, (1, 3, 2, 4, 5), (2, 3, 4, 5), {6: 2}, state=PurchaseState((1, 3), 700)
    )
    assert result.decision == "save"
    assert result.save_souls == 1700
    assert [step.item_id for step in result.actions] == [6, 1, 2, 4, 5]
    assert result.final_inventory == (3, 6, 2, 4, 5)
    assert result.actions[0].consumed_items == (1,)
    assert result.actions[1].incremental_cost == 800
    done = plan_purchases(
        graph, (1, 3, 2, 4, 5), (2, 3, 4, 5), {}, state=PurchaseState((2, 3, 4, 5), 0)
    )
    assert done.decision == "complete"
    bought = plan_purchases(graph, (3,), (3,), {}, state=PurchaseState((), 800))
    assert bought.decision == "buy"


@pytest.mark.parametrize(
    "state",
    [
        PurchaseState((1, 1)),
        PurchaseState((True,)),
        PurchaseState((), -1),
        PurchaseState(liquid_souls=True),
        PurchaseState(flex=True),
        PurchaseState((), 0, 4),
        PurchaseState(tuple(range(1, 11))),
    ],
)
def test_invalid_inventory_and_cash_are_rejected(state: PurchaseState) -> None:
    _, graph = guidance_fixture()
    with pytest.raises((ValueError, MechanicsError)):
        plan_purchases(graph, (3,), (3,), {}, state=state)


@pytest.mark.parametrize(
    "positions", [{7: -1}, {7: True}, {7: 6}, {2: 0}, {10: 3, 11: 2}]
)
def test_illegal_positions_are_rejected(positions: dict[int, int]) -> None:
    _, graph = guidance_fixture()
    with pytest.raises(ValueError, match=r"position|precedes"):
        plan_purchases(graph, (1, 3, 2, 4, 5), (2, 3, 4, 5), positions)


def test_unknown_and_infeasible_choices_stay_visible() -> None:
    guide, _ = guidance_fixture()
    missing = replace(guide, purchase_timing=())
    result = attach_purchase_guidance(missing, guidance_assets())
    assert result.purchase_guidance is not None
    assert not result.purchase_guidance.decisions
    assert len(result.purchase_guidance.choices) == 7
    assert PurchaseTiming(6, 1000, (19, 0)).position is None
    assert PurchaseTiming(6, 1000, (20, 0)).position is None
    assets = guidance_assets()
    for asset in assets:
        if asset["id"] in {2, 3, 4, 5}:
            asset["is_active_item"] = True
    blocked = attach_purchase_guidance(guide, assets)
    assert blocked.purchase_guidance is not None
    card = next(row for row in blocked.purchase_guidance.choices if row.item_id == 8)
    assert card.plan is None
    assert card.blocked_reason == "purchase exceeds four active-item bindings"
    assert "Bullet Shield** — Blocked" in build_markdown(blocked)


def test_core_upgrade_cannot_precede_its_core_component() -> None:
    guide, _ = guidance_fixture()
    assets = guidance_assets()
    assets[5] = {**assets[5], "component_items": ["Speed"], "cost": 3200}
    updated = attach_purchase_guidance(guide, assets)
    assert updated.purchase_guidance is not None
    card = updated.purchase_guidance.choices[0]
    assert card.after_step is None
    assert "precedes a required core" in card.timing_basis


def test_default_mismatch_and_missing_guidance_are_rejected() -> None:
    guide, graph = guidance_fixture()
    with pytest.raises(MechanicsError, match="differs"):
        attach_purchase_guidance(
            replace(guide, core_target_cost=100), guidance_assets()
        )
    with pytest.raises(ValueError, match="no purchase guidance"):
        build_markdown(replace(guide, purchase_guidance=None))
    with pytest.raises(MechanicsError, match="abandons"):
        plan_purchases(graph, (3,), (4,), {})
    with pytest.raises(TypeError, match="Selected"):
        plan_purchases(graph, (3,), (3,), {True: 0})
    actives = ItemGraph.from_assets([
        item(key, str(key), active=True) for key in range(1, 6)
    ])
    with pytest.raises(MechanicsError, match="active"):
        plan_purchases(actives, (1,), (1,), {}, state=PurchaseState((1, 2, 3, 4, 5)))


def test_purposes_keep_primary_effect_and_conditional_triggers() -> None:
    assert (
        purpose({"description": {"desc": ["Heal an ally", "nearby"]}}).label
        == "Ally healing"
    )
    assert (
        purpose({
            "description": "Apply a stun after 2s. Airborne targets take more."
        }).trigger
        == "You need a delayed stun; airborne targets receive a longer stun"
    )
    unknown: dict[str, object] = {
        "description": "An unclassified effect.",
        "properties": {"BonusHealth": {"value": 100}},
        "tooltip_sections": [
            {"section_attributes": [{"important_properties": ["BonusHealth"]}]}
        ],
    }
    assert purpose(unknown).basis == "unclassified"
    assert purpose({**unknown, "description": None}).label == "Health"
    assert purpose({}).label == "General utility"
