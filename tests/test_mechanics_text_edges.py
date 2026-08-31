import math

import pytest

from deadlock_build_sync import mechanics_item_text, mechanics_optional
from deadlock_build_sync.mechanics import (
    classify_item_threat_responses,
    conditional_item_decision,
    optional_item_decision,
)
from tests.mechanics_fixtures import item


@pytest.mark.parametrize(
    "properties",
    [
        None,
        {"Bad": 7},
        {"Bad": {"label": "Missing value"}},
        {"Bad": {"value": None}},
        {"Bad": {"value": ""}},
        {"Bad": {"value": 0}},
        {"Bad": {"value": "0.0"}},
    ],
)
def test_active_properties_skip_absent_or_zero_values(properties: object) -> None:
    assert (
        mechanics_item_text._active_property_mechanics({"properties": properties}) == {}
    )


def test_material_mechanics_keep_direct_structured_fields() -> None:
    asset = item(1, "structured")
    asset.update({
        "description": "Deal damage.",
        "behaviour": "active",
        "damage_type": "spirit",
        "targeting": {"kind": "enemy"},
        "weapon_info": {"ammo": 10},
    })

    mechanics = mechanics_item_text._material_observed_mechanics(asset)

    assert mechanics["description"] == "Deal damage."
    assert mechanics["behaviour"] == "active"
    assert mechanics["damage_type"] == "spirit"
    assert mechanics["targeting"] == {"kind": "enemy"}
    assert mechanics["weapon_info"] == {"ammo": 10}


@pytest.mark.parametrize(
    ("property_type", "label", "expected_response", "expected_copy"),
    [
        (
            "MODIFIER_VALUE_BULLET_ARMOR_DAMAGE_RESIST",
            "",
            "bullet_pressure",
            "Bullet Resist",
        ),
        (
            "MODIFIER_VALUE_BULLET_SHIELD",
            "Barrier",
            "bullet_pressure",
            "Barrier",
        ),
        (
            "MODIFIER_VALUE_FIRE_RATE_SLOW",
            "",
            "bullet_pressure",
            "Fire Rate Slow",
        ),
        (
            "MODIFIER_VALUE_SPIRIT_ARMOR_DAMAGE_RESIST",
            "",
            "spirit_burst",
            "Spirit Resist",
        ),
        (
            "MODIFIER_VALUE_SPIRIT_SHIELD",
            "Ward",
            "spirit_burst",
            "Ward",
        ),
    ],
)
def test_typed_properties_map_to_stable_response_copy(
    property_type: str,
    label: str,
    expected_response: str,
    expected_copy: str,
) -> None:
    asset = item(1, "typed")
    asset["properties"] = {
        "Mechanic": {
            "provided_property_type": property_type,
            "label": label,
            "tooltip_is_important": True,
            "value": 1,
        }
    }

    assert mechanics_item_text._response_mechanic_labels(asset)[expected_response] == (
        expected_copy,
    )


@pytest.mark.parametrize(
    ("label", "expected_response", "expected_copy"),
    [
        ("Bullet Shield", "bullet_pressure", "Bullet Shield"),
        ("Spirit Shield", "spirit_burst", "Spirit Shield"),
    ],
)
def test_untyped_shield_labels_map_to_responses(
    label: str,
    expected_response: str,
    expected_copy: str,
) -> None:
    asset = item(1, "shield")
    asset["properties"] = {
        "Shield": {
            "label": label,
            "tooltip_is_important": True,
            "value": 10,
        }
    }

    assert mechanics_item_text._response_mechanic_labels(asset)[expected_response] == (
        expected_copy,
    )


def test_response_copy_deduplicates_property_and_description_labels() -> None:
    asset = item(1, "resist")
    asset["description"] = {"desc": "Gain Bullet Resist."}
    asset["properties"] = {
        "Resist": {
            "provided_property_type": "MODIFIER_VALUE_BULLET_ARMOR_DAMAGE_RESIST",
            "tooltip_is_important": True,
            "value": 10,
        }
    }

    assert mechanics_item_text._response_mechanic_labels(asset)["bullet_pressure"] == (
        "Bullet Resist",
    )


@pytest.mark.parametrize(
    ("properties", "name"),
    [
        (None, "Duration"),
        ({"Duration": 7}, "Duration"),
        ({"Duration": {"value": []}}, "Duration"),
        ({"Duration": {"value": "not-number"}}, "Duration"),
        ({"Duration": {"value": math.inf}}, "Duration"),
    ],
)
def test_property_number_rejects_non_numeric_or_non_finite_values(
    properties: object,
    name: str,
) -> None:
    assert mechanics_optional._property_number({"properties": properties}, name) is None


def test_channel_protection_needs_complete_matching_ability_data() -> None:
    control_item = item(1, "control_immunity")
    control_item["description"] = {"desc": "Gain Control Immunity."}
    control_item["properties"] = {"AbilityDuration": {"value": 3}}

    assert optional_item_decision(control_item, hero_mechanics={}) == (
        "Enemy control blocks your next commit",
        "Control Immunity",
        "Damage or mobility matters more",
    )
    assert optional_item_decision(
        control_item,
        hero_mechanics={
            "abilities": [
                {"id": "bad", "slot": 1, "name": "Bad"},
                {"id": 2, "slot": "bad", "name": "Bad"},
                {"id": 3, "slot": 3, "name": ""},
                {
                    "id": 4,
                    "slot": 4,
                    "name": "Too Long",
                    "properties": {"AbilityChannelTime": {"value": 4}},
                },
            ]
        },
    ) == (
        "Enemy control blocks your next commit",
        "Control Immunity",
        "Damage or mobility matters more",
    )


def test_channel_protection_prefers_an_ultimate_then_stable_slot_order() -> None:
    control_item = item(1, "control_immunity")
    control_item["description"] = {"desc": "Gain Control Immunity."}
    control_item["properties"] = {"AbilityDuration": {"value": 5}}
    hero: dict[str, object] = {
        "abilities": [
            {
                "id": 10,
                "slot": 1,
                "name": "Basic Channel",
                "properties": {"AbilityChannelTime": {"value": 2}},
            },
            {
                "id": 40,
                "slot": 4,
                "name": "Ultimate Channel",
                "properties": {"AbilityChannelTime": {"value": 4}},
            },
        ]
    }

    assert optional_item_decision(control_item, hero_mechanics=hero) == (
        "Activate before Ultimate Channel when enemy control can interrupt it",
        "Control Immunity protects the channel",
        "Enemy control cannot threaten Ultimate Channel",
    )


def test_conditional_decision_rejects_bad_response_or_comparator() -> None:
    resist = item(1, "resist")
    resist["description"] = {"desc": "Gain Spirit Resist."}
    neutral = item(2, "neutral")
    neutral["description"] = {"desc": "A plain item."}

    assert conditional_item_decision(neutral, resist) is None
    assert conditional_item_decision(resist, neutral) is None
    assert conditional_item_decision(resist, resist, response="healing") is None


def test_conditional_decision_marks_ally_only_target_copy() -> None:
    ally_resist = item(1, "ally_resist")
    ally_resist["description"] = {"desc": "Give Spirit Resist to a friendly target."}
    weapon = item(2, "weapon")
    weapon["description"] = {"desc": "Gain Weapon Damage."}

    assert conditional_item_decision(ally_resist, weapon) == (
        "Heavy Spirit damage",
        "Spirit Resist for ally",
        "Before the next Spirit-heavy fight",
        "Keep default when weapon pressure matters more",
    )


def test_slow_immunity_is_not_treated_as_an_offensive_slow() -> None:
    asset = item(1, "slow_immunity")
    asset["description"] = {"desc": "Gain movement slow immunity."}

    assert classify_item_threat_responses(asset) == frozenset({"slow_resistance"})
