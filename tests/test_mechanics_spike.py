import pytest

from deadlock_build_sync.mechanics import power_spike_text
from tests.mechanics_fixtures import item

SPIRIT_DAMAGE: dict[str, object] = {
    "class_name": "scale_function_tech_damage",
    "specific_stat_scale_type": "ETechPower",
    "stat_scale": 0.6,
}


def spirit_item(
    *,
    important: bool = True,
    slot: str = "spirit",
    value: str = "20",
    stat: str = "SpiritPower",
) -> dict[str, object]:
    asset = item(99, "spirit_item")
    asset["item_slot_type"] = slot
    asset["properties"] = {
        stat: {
            "label": "Spirit Power",
            "provided_property_type": "MODIFIER_VALUE_TECH_POWER",
            "tooltip_is_important": important,
            "value": value,
        }
    }
    return asset


def ability(
    slot: int,
    name: str,
    properties: dict[str, object],
) -> dict[str, object]:
    return {"id": slot * 10, "slot": slot, "name": name, "properties": properties}


def scaled(value: object, scale: dict[str, object]) -> dict[str, object]:
    return {"value": value, "disable_value": "0", "scale_function": scale}


def kit(*abilities: dict[str, object]) -> dict[str, object]:
    return {"abilities": list(abilities)}


def napalm() -> dict[str, object]:
    return kit(ability(1, "Napalm", {"Damage": scaled(40.0, SPIRIT_DAMAGE)}))


def test_spirit_slot_item_names_the_ability_that_scales_with_it() -> None:
    assert power_spike_text(spirit_item(), napalm(), max_chars=80) == (
        "Napalm spirit x0.6"
    )


def test_tech_damage_class_without_coefficient_has_no_multiplier() -> None:
    hero = kit(
        ability(
            2,
            "Flame Dash",
            {"DPS": scaled(30.0, {"class_name": "scale_function_tech_damage"})},
        )
    )

    assert power_spike_text(spirit_item(), hero, max_chars=80) == "Flame Dash spirit"


def test_enemy_spirit_reduction_is_never_a_spike() -> None:
    debuff = spirit_item(stat="TechPowerReduction", value="-30")

    assert not power_spike_text(debuff, napalm(), max_chars=80)


@pytest.mark.parametrize(
    "stat",
    ["ImbuedTechPower", "TechPowerGain", "AmbushBonusTechPower"],
)
def test_conditional_grants_are_not_flat_spirit_power(stat: str) -> None:
    conditional = spirit_item(stat=stat, value="28")

    assert not power_spike_text(conditional, napalm(), max_chars=80)


def test_off_slot_rider_needs_a_large_grant() -> None:
    rider = spirit_item(slot="vitality", value="20")
    primary = spirit_item(slot="vitality", value="30")

    assert not power_spike_text(rider, napalm(), max_chars=80)
    assert power_spike_text(primary, napalm(), max_chars=80) == "Napalm spirit x0.6"


def test_largest_qualifying_grant_decides_an_off_slot_item() -> None:
    asset = item(98, "mixed")
    asset["item_slot_type"] = "weapon"
    asset["properties"] = {
        "SpiritPowerInnate": {
            "provided_property_type": "MODIFIER_VALUE_TECH_POWER",
            "tooltip_is_important": True,
            "value": "5",
        },
        "BonusSpirit": {
            "provided_property_type": "MODIFIER_VALUE_TECH_POWER",
            "tooltip_is_important": True,
            "value": "40",
        },
    }

    assert power_spike_text(asset, napalm(), max_chars=80) == "Napalm spirit x0.6"


def test_zero_valued_scale_properties_do_not_create_a_spike() -> None:
    hero = kit(
        ability(
            1,
            "Napalm",
            {
                "Damage": scaled("0", SPIRIT_DAMAGE),
                "AbilityDuration": scaled(0, SPIRIT_DAMAGE),
            },
        )
    )

    assert not power_spike_text(spirit_item(), hero, max_chars=80)


def test_non_important_stat_missing_kit_and_plain_item_give_no_spike() -> None:
    assert not power_spike_text(spirit_item(important=False), napalm(), max_chars=80)
    assert not power_spike_text(spirit_item(), None, max_chars=80)
    assert not power_spike_text(item(96, "plain"), napalm(), max_chars=80)


def test_cooldown_and_range_items_no_longer_qualify() -> None:
    cooldown_item = item(95, "cooldown")
    cooldown_item["item_slot_type"] = "spirit"
    cooldown_item["properties"] = {
        "CooldownReduction": {
            "provided_property_type": "MODIFIER_VALUE_COOLDOWN_REDUCTION_PERCENTAGE",
            "tooltip_is_important": True,
            "value": "20",
        }
    }
    hero = kit(
        ability(
            3,
            "Afterburn",
            {
                "AbilityCooldown": scaled(
                    25.0,
                    {"specific_stat_scale_type": "ETechCooldown"},
                )
            },
        )
    )

    assert not power_spike_text(cooldown_item, hero, max_chars=80)


def test_malformed_ability_rows_are_skipped() -> None:
    hero = kit(
        {"id": 10, "slot": "one", "name": "Bad Slot", "properties": {}},
        {"id": 20, "slot": 2, "name": "", "properties": {}},
        {
            "id": 30,
            "slot": 3,
            "name": "No Scale",
            "properties": {"Damage": {"value": 5}},
        },
        {"id": 40, "slot": 4, "name": "No Props"},
        ability(1, "Napalm", {"Damage": scaled(40.0, SPIRIT_DAMAGE)}),
    )

    assert power_spike_text(spirit_item(), hero, max_chars=80) == "Napalm spirit x0.6"


def test_two_strongest_abilities_are_named_in_coefficient_order() -> None:
    hero = kit(
        ability(1, "Napalm", {"Damage": scaled(40.0, SPIRIT_DAMAGE)}),
        ability(
            2,
            "Flame Dash",
            {"DPS": scaled(30.0, {**SPIRIT_DAMAGE, "stat_scale": 0.7})},
        ),
        ability(
            4,
            "Concussive Combustion",
            {
                "Damage": scaled(100.0, {**SPIRIT_DAMAGE, "stat_scale": 0.974}),
                "DPS": scaled(10.0, {**SPIRIT_DAMAGE, "stat_scale": 0.1}),
            },
        ),
    )

    assert power_spike_text(spirit_item(), hero, max_chars=80) == (
        "Concussive Combustion spirit x0.97 · Flame Dash spirit x0.7"
    )


def test_budget_falls_back_to_one_ability_then_to_nothing() -> None:
    hero = kit(
        ability(1, "Napalm", {"Damage": scaled(40.0, SPIRIT_DAMAGE)}),
        ability(2, "Flame Dash", {"DPS": scaled(30.0, SPIRIT_DAMAGE)}),
    )

    assert power_spike_text(spirit_item(), hero, max_chars=20) == "Napalm spirit x0.6"
    assert not power_spike_text(spirit_item(), hero, max_chars=10)
