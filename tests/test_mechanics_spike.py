from deadlock_build_sync.mechanics import power_spike_text
from tests.mechanics_fixtures import item


def spirit_item(*, important: bool = True) -> dict[str, object]:
    asset = item(99, "extra_spirit")
    asset["properties"] = {
        "TechPower": {
            "label": "Spirit Power",
            "provided_property_type": "MODIFIER_VALUE_TECH_POWER",
            "tooltip_is_important": important,
            "value": "10",
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


SPIRIT_DAMAGE: dict[str, object] = {
    "class_name": "scale_function_tech_damage",
    "specific_stat_scale_type": "ETechPower",
    "stat_scale": 0.6,
}


def kit(*abilities: dict[str, object]) -> dict[str, object]:
    return {"abilities": list(abilities)}


def test_spirit_item_names_the_ability_with_spirit_damage_scaling() -> None:
    hero = kit(ability(1, "Napalm", {"Damage": scaled(40.0, SPIRIT_DAMAGE)}))

    assert power_spike_text(spirit_item(), hero, max_chars=80) == "Napalm spirit x0.6"


def test_tech_damage_class_without_coefficient_has_no_multiplier() -> None:
    hero = kit(
        ability(
            2,
            "Flame Dash",
            {"DPS": scaled(30.0, {"class_name": "scale_function_tech_damage"})},
        )
    )

    assert power_spike_text(spirit_item(), hero, max_chars=80) == "Flame Dash spirit"


def test_cooldown_and_duration_items_match_their_scale_types() -> None:
    cooldown_item = item(98, "cooldown")
    cooldown_item["properties"] = {
        "CooldownReduction": {
            "provided_property_type": "MODIFIER_VALUE_COOLDOWN_REDUCTION_PERCENTAGE",
            "tooltip_is_important": True,
            "value": "20",
        }
    }
    duration_item = item(97, "duration")
    duration_item["properties"] = {
        "BonusAbilityDuration": {
            "provided_property_type": (
                "MODIFIER_VALUE_BONUS_ABILITY_DURATION_PERCENTAGE"
            ),
            "tooltip_is_important": True,
            "value": "15",
        }
    }
    hero = kit(
        ability(
            3,
            "Afterburn",
            {
                "AbilityCooldown": scaled(
                    25.0,
                    {
                        "class_name": "scale_function_single_stat",
                        "specific_stat_scale_type": "ETechCooldown",
                    },
                ),
                "AbilityChannelTime": scaled(
                    "2",
                    {
                        "class_name": "scale_function_multi_stats",
                        "scaling_stats": ["EChannelDuration", "ETechDuration"],
                    },
                ),
            },
        )
    )

    assert power_spike_text(cooldown_item, hero, max_chars=80) == "Afterburn cooldown"
    assert power_spike_text(duration_item, hero, max_chars=80) == "Afterburn duration"


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


def test_non_important_item_stat_and_missing_kit_give_no_spike() -> None:
    hero = kit(ability(1, "Napalm", {"Damage": scaled(40.0, SPIRIT_DAMAGE)}))

    assert not power_spike_text(spirit_item(important=False), hero, max_chars=80)
    assert not power_spike_text(spirit_item(), None, max_chars=80)
    assert not power_spike_text(item(96, "plain"), hero, max_chars=80)


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
