import pytest

from deadlock_build_sync.mechanics import (
    classify_item_threat_responses,
    classify_observed_item_threats,
    conditional_item_decision,
)
from tests.mechanics_fixtures import item


@pytest.mark.parametrize(
    ("description", "expected"),
    [
        ("Restore Health to an ally.", "healing"),
        ("Gain Weapon Damage.", "bullet_pressure"),
        ("Gain Spirit Power.", "spirit_pressure"),
        ("Apply a Stun after a delay.", "control"),
        ("Teleport to the target.", "mobility_escape"),
        ("Shield an ally.", "ally_protection"),
    ],
)
def test_observed_enemy_item_threats_require_explicit_mechanics(
    description: str,
    expected: str,
) -> None:
    asset = item(99, "threat")
    asset["description"] = {"desc": description}

    assert expected in classify_observed_item_threats(asset)


def test_anti_heal_is_not_mislabeled_as_enemy_healing() -> None:
    asset = item(99, "anti_heal")
    asset["description"] = {"desc": "Applies healing reduction."}

    assert "healing" not in classify_observed_item_threats(asset)


def test_disabled_property_labels_do_not_create_observed_threats() -> None:
    asset = item(99, "neutral")
    asset["properties"] = {
        "WeaponPower": {
            "label": "Weapon Damage",
            "value": "0",
            "disable_value": "0",
        },
        "TechPower": {
            "label": "Spirit Power",
            "value": "0",
            "disable_value": "0",
        },
    }

    assert classify_observed_item_threats(asset) == frozenset()


def test_disabled_property_labels_do_not_create_counter_responses() -> None:
    asset = item(99, "neutral")
    asset["properties"] = {
        "BulletResist": {
            "label": "Bullet Resist",
            "value": "0",
            "disable_value": "0",
        },
        "SpiritShield": {
            "label": "Spirit Shield",
            "value": "0",
            "disable_value": "0",
        },
    }

    assert classify_item_threat_responses(asset) == frozenset()


def test_only_important_typed_properties_create_observed_threats() -> None:
    asset = item(99, "spirit")
    asset["properties"] = {
        "TechPower": {
            "label": "Spirit Power",
            "value": "18",
            "disable_value": "0",
            "tooltip_is_important": False,
        }
    }

    assert classify_observed_item_threats(asset) == frozenset()

    asset["properties"]["TechPower"]["tooltip_is_important"] = True

    assert classify_observed_item_threats(asset) == frozenset({"spirit_pressure"})


def test_hidden_minor_resist_does_not_make_melee_charge_a_bullet_response() -> None:
    asset = item(99, "melee_charge")
    asset["description"] = {"desc": "Charge a heavy melee attack faster."}
    asset["properties"] = {
        "BulletResist": {
            "label": "Bullet Resist",
            "provided_property_type": "MODIFIER_VALUE_BULLET_ARMOR_DAMAGE_RESIST",
            "tooltip_is_important": False,
            "value": "0.06",
        }
    }

    assert "bullet_pressure" not in classify_item_threat_responses(asset)


def test_enemy_resist_reduction_is_not_a_defensive_response() -> None:
    hunter_aura = item(99, "hunters_aura")
    hunter_aura["description"] = {
        "desc": "Reduces nearby enemies' Bullet Resist and Fire Rate."
    }
    hunter_aura["properties"] = {
        "BulletArmorReduction": {
            "label": "Enemy Bullet Resist",
            "provided_property_type": "MODIFIER_VALUE_BULLET_ARMOR_RESIST_REDUCTION",
            "tooltip_is_important": True,
            "value": "-0.12",
        },
        "FireRateSlow": {
            "label": "Enemy Fire Rate Slow",
            "provided_property_type": "MODIFIER_VALUE_FIRE_RATE_SLOW",
            "tooltip_is_important": True,
            "value": "0.15",
        },
    }
    comparator = item(100, "weapon_item")
    comparator["description"] = {"desc": "Gain Weapon Damage."}

    assert classify_item_threat_responses(hunter_aura) == frozenset({"bullet_pressure"})
    assert conditional_item_decision(hunter_aura, comparator) == (
        "Heavy bullet damage",
        "Fire Rate Slow",
        "Before the next bullet-heavy fight",
        "Keep default when weapon pressure matters more",
    )


def test_bullet_resist_reduction_label_is_not_bullet_defense() -> None:
    shredder = item(99, "bullet_resist_shredder")
    shredder["description"] = {"desc": "Reduces Bullet Resist on enemies."}
    shredder["properties"] = {
        "BulletArmorReduction": {
            "label": "Bullet Resist",
            "tooltip_is_important": True,
            "value": "-10",
        }
    }

    assert "bullet_pressure" not in classify_item_threat_responses(shredder)


def test_automatically_does_not_create_ally_protection() -> None:
    active_reload = item(99, "active_reload")
    active_reload["description"] = {
        "desc": "Automatically finish reloading and gain Bullet Lifesteal."
    }

    assert "ally_protection" not in classify_item_threat_responses(active_reload)


def test_upgrade_only_ability_text_does_not_create_enemy_threat() -> None:
    rising_ram = item(99, "rising_ram")
    rising_ram["type"] = "ability"
    rising_ram["description"] = {
        "desc": "Charge forward and knock enemies upward.",
        "t1_desc": "+25% Weapon Damage for 5s.",
    }

    assert "bullet_pressure" not in classify_observed_item_threats(rising_ram)

    assassinate = item(100, "assassinate")
    assassinate["type"] = "ability"
    assassinate["description"] = {
        "desc": "Deal damage with bonus Weapon Damage against wounded targets."
    }

    assert "bullet_pressure" in classify_observed_item_threats(assassinate)
