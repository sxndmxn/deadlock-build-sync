from dataclasses import replace

from deadlock_build_sync.policy import BuildPolicy
from deadlock_build_sync.service import generate_guides
from deadlock_build_sync.strategy_context import (
    build_strategy_context_document,
    validate_strategy_context_document,
)
from deadlock_build_sync.value_validation import (
    require_object_dict,
    require_object_rows,
)
from tests.service_evidence_fixtures import build_evidence
from tests.service_fake_api import FakeApi, ability_rows, duration_points


def test_required_components_join_core_queue_and_leave_optional_rows() -> None:
    api = FakeApi(ability_rows=ability_rows(), duration_points=duration_points())
    parent = next(item for item in api._assets if item.get("id") == 200)
    parent["component_items"] = ["item_1_2"]

    generated = generate_guides(
        api,
        build_evidence=build_evidence(api, with_component_path=True),
        account_id=123,
        hero_query="Kelvin",
        all_heroes=False,
    )

    guide = generated.guides[0]
    assert [item.item_id for item in guide.categories[0].items] == [
        100,
        101,
        102,
        200,
        201,
        300,
        301,
        400,
        401,
    ]
    assert [item.item_id for item in guide.core_items] == [
        100,
        101,
        200,
        201,
        300,
        301,
        400,
        401,
    ]
    assert 102 not in {item.item_id for item in guide.categories[1].items}
    projection = require_object_dict(generated.contexts[0]["projection"])
    categories = require_object_rows(projection["categories"])
    projected_items = require_object_rows(categories[0]["items"])
    assert projected_items[2]["item_id"] == 102


def test_admitted_situational_branch_reaches_policy_sidecar_and_tier_card() -> None:
    api = FakeApi(ability_rows=ability_rows(), duration_points=duration_points())
    generated = generate_guides(
        api,
        build_evidence=build_evidence(api, with_situational_branch=True),
        account_id=123,
        hero_query="Kelvin",
        all_heroes=False,
    )

    guide = generated.guides[0]
    policy = generated.policies[0]
    assert policy.entry == "situational-choice-1"
    assert BuildPolicy.from_dict(policy.as_dict()) == policy
    assert len(policy.counter_cards) == 1
    choice = next(node for node in policy.nodes if node.node_id == policy.entry)
    assert [guard.field for guard in choice.branches[0].guards] == [
        "enemy.threats",
        "enemy.lane_heroes",
        "clock_s",
        "clock_s",
    ]
    situational = next(node for node in policy.nodes if node.node_id == "situational-1")
    assert situational.next_id == "core-2"
    assert choice.branches[-1].next_id == "core-1"
    tier_item = next(item for item in guide.tiers[1] if item.item_id == 103)
    assert tier_item.annotation == (
        "VS: Heavy enemy healing\n"
        "WHY: Healing Reduction\n"
        "SWAP: Replaces Tier 1 Item 0\n"
        "WHEN: Before the next fight with heavy enemy healing\n"
        "SKIP: Keep default when weapon pressure matters more"
    )
    assert "WIN RATE" not in tier_item.annotation
    assert [category.name for category in guide.categories] == [
        "CORE ITEMS",
        "TIER 1",
        "TIER 2",
        "TIER 3",
        "TIER 4",
    ]
    assert [category.optional for category in guide.categories] == [
        False,
        True,
        True,
        True,
        True,
    ]
    actions = require_object_rows(generated.contexts[0]["explainable_actions"])
    action = next(row for row in actions if row["node_id"] == "situational-1")
    contract = require_object_dict(action["conditional_contract"])
    assert contract["comparator_item"] == "Tier 1 Item 0"


def test_normal_tier_items_have_tactical_first_annotations() -> None:
    api = FakeApi(ability_rows=ability_rows(), duration_points=duration_points())
    generated = generate_guides(
        api,
        build_evidence=build_evidence(api),
        account_id=123,
        hero_query="Kelvin",
        all_heroes=False,
    )

    tier_items = [
        item for items in generated.guides[0].tiers.values() for item in items
    ]
    assert tier_items
    assert all(item.annotation.startswith("USE: ") for item in tier_items)
    assert all("\nWHY: " in item.annotation for item in tier_items)
    assert all("\nSKIP: " in item.annotation for item in tier_items)
    assert all("\nDATA: " in item.annotation for item in tier_items)
    assert all("WIN RATE" not in item.annotation for item in tier_items)


def test_control_immunity_tier_item_uses_the_hero_channel() -> None:
    api = FakeApi(ability_rows=ability_rows(), duration_points=duration_points())
    api._hero["name"] = "Dynamo"
    singularity = next(asset for asset in api._assets if asset["id"] == 40)
    singularity["name"] = "Singularity"
    singularity["properties"] = {
        "AbilityChannelTime": {"value": "3.5", "disable_value": "0"}
    }
    unstoppable = next(asset for asset in api._assets if asset["id"] == 402)
    unstoppable["name"] = "Unstoppable"
    unstoppable["description"] = {
        "desc": (
            "Temporarily suppress negative status effects and become immune to "
            "Stun, Silence, Sleep, Root, and Disarm. Cannot be used while Stunned "
            "or Slept."
        )
    }
    unstoppable["properties"] = {
        "AbilityDuration": {
            "label": "Duration",
            "tooltip_is_important": True,
            "value": "5.5",
        }
    }
    catalog = build_evidence(api)
    hero = replace(catalog.heroes[12], hero="Dynamo")
    generated = generate_guides(
        api,
        build_evidence=replace(catalog, heroes={12: hero}),
        account_id=123,
        hero_query="Dynamo",
        all_heroes=False,
    )

    item = next(item for item in generated.guides[0].tiers[4] if item.item_id == 402)
    assert item.annotation.splitlines()[:3] == [
        "USE: Activate before Singularity when enemy control can interrupt it",
        "WHY: Control Immunity protects the channel",
        "SKIP: Enemy control cannot threaten Singularity",
    ]
    assert "Disarm" not in item.annotation
    assert "catch" not in item.annotation.casefold()


def test_admitted_core_alternative_is_a_non_queue_policy_card() -> None:
    api = FakeApi(ability_rows=ability_rows(), duration_points=duration_points())
    generated = generate_guides(
        api,
        build_evidence=build_evidence(api, with_core_alternative=True),
        account_id=123,
        hero_query="Kelvin",
        all_heroes=False,
    )

    guide = generated.guides[0]
    policy = generated.policies[0]
    assert policy.schema_version == 5
    assert [card.item_id for card in policy.core_alternatives] == [103]
    assert [category.name for category in guide.categories] == [
        "CORE ITEMS",
        "OPTIONAL CORE",
        "TIER 1",
        "TIER 2",
        "TIER 3",
        "TIER 4",
    ]
    assert [item.item_id for item in guide.categories[1].items] == [103]
    assert guide.categories[1].items[0].annotation == (
        "VS: Heavy enemy healing\n"
        "WHY: Healing Reduction\n"
        "SWAP: Replaces Tier 1 Item 1\n"
        "WHEN: Before the next fight with heavy enemy healing\n"
        "SKIP: Keep default when weapon pressure matters more"
    )
    assert "WIN RATE" not in guide.categories[1].items[0].annotation
    assert 103 not in {item.item_id for item in guide.tiers[1]}
    assert all(node.item_id != 103 for node in policy.nodes)
    assert BuildPolicy.from_dict(policy.as_dict()) == policy

    document = build_strategy_context_document(
        generated.patch,
        list(generated.contexts),
        manifest=generated.manifest,
        item_mechanics=generated.item_mechanics,
        requested_hero_ids=set(generated.eligible_hero_ids),
        exclusions=generated.exclusions,
    )
    validate_strategy_context_document(document)
