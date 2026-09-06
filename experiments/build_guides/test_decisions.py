"""Regressions for primary effects, upgrade decisions, and unknown timing."""

from __future__ import annotations

from copy import deepcopy

import pytest

from experiments.build_guides.assemble import assemble
from experiments.build_guides.audit import audit_decisions
from experiments.build_guides.decisions import attach_decisions, decisions_for
from experiments.build_guides.paths import plan
from experiments.build_guides.purposes import purpose
from experiments.build_guides.render import markdown
from experiments.build_guides.schema import adapt_legacy
from experiments.build_guides.test_build_guides import (
    evidence_fixture,
    graph_fixture,
    guide_fixture,
    row_fixture,
)


@pytest.mark.parametrize(
    ("description", "expected"),
    [
        (
            "Heals a target allied hero and yourself. You can Pull the target towards you.",
            "Ally healing",
        ),
        (
            "Apply a Stun after 2s. Stun duration is increased against airborne targets.",
            "Hard control",
        ),
        (
            "Dealing significant spirit damage causes an explosion and burn. Enemies receive reduced healing.",
            "Healing reduction",
        ),
        ("While above 65% health, gain weapon damage and fire rate.", "Weapon damage"),
        (
            "Reduces Bullet Resist on enemies when you deal spirit damage.",
            "Bullet resistance reduction",
        ),
    ],
)
def test_main_effect_beats_minor_range_stat(description: str, expected: str) -> None:
    asset = {
        "description": {"desc": description},
        "properties": {"TechRangeMultiplier": {"value": "5"}},
    }
    assert purpose(asset)["purpose"] == expected
    assert purpose(asset)["purpose_basis"] == "primary effect text"


def test_stat_only_item_requires_material_tooltip_field() -> None:
    asset = {
        "properties": {
            "BonusAbilityCharges": {"value": "1"},
            "TechRangeMultiplier": {"value": "5"},
        }
    }
    assert purpose(asset)["purpose"] == "General utility"

    asset["tooltip_sections"] = [
        {"section_attributes": [{"elevated_properties": ["BonusAbilityCharges"]}]}
    ]
    assert purpose(asset)["purpose"] == "Ability charges"
    asset["description"] = {"desc": "An effect that has no known classification"}
    assert purpose(asset)["purpose"] == "General utility"


def test_condition_copy_keeps_the_health_threshold_and_ultimate_trigger() -> None:
    health = purpose({
        "description": {
            "desc": "While above 65% health, gain weapon damage and fire rate."
        }
    })
    assert "65%" in health["triggers"][0]
    ultimate = purpose({
        "description": {
            "desc": "Damage from your ultimate applies a stun after a short delay."
        }
    })
    assert "ultimate" in ultimate["triggers"][0]


def test_singleton_is_optional_and_general_utility_is_not_a_comparison() -> None:
    guide, graph = guide_fixture()
    cards = {row["item_id"]: row for row in guide["choices"]}
    assert decisions_for([cards[11]], graph)[0]["kind"] == "optional"
    groups = decisions_for([cards[11], cards[12]], graph)
    assert len(groups) == 2
    assert all(row["kind"] == "optional" for row in groups)


def test_all_matching_options_are_visible_without_a_shortlist_cap() -> None:
    guide, graph = guide_fixture()
    cards = [row for row in guide["choices"] if 11 <= row["item_id"] <= 15]
    for card in cards:
        card["purpose"] = "Hard control"
    decisions = decisions_for(cards, graph)
    assert len(decisions) == 1
    assert decisions[0]["kind"] == "pick_one"
    assert {row["item_id"] for row in decisions[0]["options"]} == set(range(11, 16))


def test_component_and_parent_are_one_route_not_competing_options() -> None:
    guide, graph = guide_fixture()
    cards = [row for row in guide["choices"] if row["item_id"] in {9, 10}]
    decisions = decisions_for(cards, graph)
    assert len(decisions) == 1
    assert decisions[0]["kind"] == "upgrade"
    assert decisions[0]["options"][0]["route"] == [9, 10]
    assert decisions[0]["options"][0]["choice_items"] == [9, 10]
    assert decisions[0]["options"][0]["stages"] == [
        {"item_id": 9, "extra_path_cost": 1600},
        {"item_id": 10, "extra_path_cost": 3200},
    ]


def test_shared_component_fork_is_an_explicit_upgrade_choice() -> None:
    guide, graph = guide_fixture()
    card = deepcopy(next(row for row in guide["choices"] if row["item_id"] == 8))
    sibling = {**card, "item_id": 5, "purpose": "Different need"}
    result = decisions_for([card, sibling], graph)[0]
    assert result["kind"] == "pick_one"
    assert result["relationship"] == "upgrade_fork"
    assert {tuple(row["route"]) for row in result["options"]} == {(4, 5), (4, 8)}


def test_unknown_timing_stays_in_pool_and_requires_an_explicit_position() -> None:
    evidence, graph = evidence_fixture(), graph_fixture()
    for history in evidence["histories"].values():
        history[9] = history[3]
    assets = {item: {"description": {"desc": "Effect"}} for item in graph.nodes}
    guide = assemble(row_fixture(), graph, assets, evidence)
    card = next(row for row in guide["choices"] if row["item_id"] == 9)
    assert card["placement"]["after_step"] is None
    assert card["branch"] is None
    assert 9 in guide["item_pool"]["2"]
    assert 9 in guide["unplaced_choices"]
    assert all(9 not in cp["choices"] for cp in guide["checkpoints"])
    with pytest.raises(ValueError, match="Timing unknown"):
        plan(graph, guide, [9])
    result = plan(graph, guide, [9], placement_overrides={"9": 3})
    assert result["selected_placements"]["9"] == {
        "after_step": 3,
        "basis": "explicit override",
    }
    assert result["remaining_cost"] == 9600
    audit_decisions(guide, graph)


@pytest.mark.parametrize(
    "overrides", [{"7": 0}, {"7": -1}, {"7": 8}, {"7": True}, {"7": "6"}, {"9": 3}, []]
)
def test_override_rejects_invalid_positions_and_core_prerequisite_violations(
    overrides: dict,
) -> None:
    guide, graph = guide_fixture()
    with pytest.raises((ValueError, TypeError), match=r"[Pp]osition|[Pp]lacement"):
        plan(graph, guide, [7], placement_overrides=overrides)


def test_override_can_upgrade_an_already_owned_core_item_now() -> None:
    guide, graph = guide_fixture()
    result = plan(graph, guide, [7], owned=[2], placement_overrides={"7": 0})
    assert result["actions"][0]["item_id"] == 7
    assert result["actions"][0]["incremental_cost"] == 4800


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "Dealing significant weapon damage replenishes a charge for each of your charged abilities.",
            "Restore ability charges",
        ),
        (
            "Your bullets temporarily steal Max HP from enemies. Enemies regain their stolen health when the debuff expires.",
            "Health steal from shots",
        ),
        (
            "When in close range to your target, gain Weapon Damage and your bullets apply a Movement Slow.",
            "Close range weapon damage",
        ),
    ],
)
def test_offensive_effects_are_not_mistaken_for_defense_or_healing(
    text: str, expected: str
) -> None:
    assert purpose({"description": {"desc": text}})["purpose"] == expected


def test_selected_component_cannot_follow_its_upgrade() -> None:
    guide, graph = guide_fixture()
    with pytest.raises(ValueError, match="precedes its selected component"):
        plan(graph, guide, [9, 10], placement_overrides={"9": 6, "10": 3})
    result = plan(graph, guide, [9, 10], placement_overrides={"9": 3, "10": 3})
    assert [row["item_id"] for row in result["actions"]].count(9) == 1


def test_legacy_adaptation_does_not_modify_original_or_keep_unsupported_branch() -> (
    None
):
    original, graph = guide_fixture()
    original["schema_version"] = 1
    card = next(row for row in original["choices"] if row["item_id"] == 9)
    card["placement"].update({"supported": False, "after_step": 6})
    before = deepcopy(original)
    assets = {item: {"description": {"desc": "Effect"}} for item in graph.nodes}
    adapted = adapt_legacy(original, graph, assets)
    assert original == before
    assert adapted["schema_version"] == 2
    assert adapted["source_schema_version"] == 1
    assert adapted["core_validation"] == original["core_validation"]
    assert adapted["item_pool"] == original["item_pool"]
    assert 9 in adapted["unplaced_choices"]
    assert (
        next(row for row in adapted["choices"] if row["item_id"] == 9)["branch"] is None
    )


def test_markdown_default_has_full_pool_without_long_branch_details() -> None:
    guide, graph = guide_fixture()
    for card in guide["choices"]:
        if 11 <= card["item_id"] <= 15:
            card["purpose"] = "Hard control"
    attach_decisions(guide, graph)
    text = markdown(guide)
    assert "PICK ONE — Hard control" in text
    assert "Path with this choice" not in text
    assert "Path with this choice" in markdown(guide, details=True)
    assert all(card["name"] in text for card in guide["choices"])
    audit_decisions(guide, graph)
