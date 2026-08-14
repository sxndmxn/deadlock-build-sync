from typing import Any

import pytest

from deadlock_build_sync.mechanics import (
    AbilityAction,
    AbilityDefinition,
    CategoryBonusTable,
    InventoryState,
    ItemGraph,
    MechanicsError,
    ability_definitions_from_kit,
    build_hero_mechanics,
    classify_item_threat_responses,
    classify_observed_item_threats,
    purchase_item,
    sell_item,
    validate_ability_timeline,
    validate_imbue,
)


def item(
    item_id: int,
    class_name: str,
    *,
    cost: int = 500,
    components: list[str] | None = None,
    active: bool = False,
) -> dict[str, Any]:
    return {
        "id": item_id,
        "class_name": class_name,
        "name": class_name,
        "cost": cost,
        "component_items": components or [],
        "item_slot_type": "weapon",
        "item_tier": 1,
        "shopable": True,
        "disabled": False,
        "is_active_item": active,
    }


def test_kit_record_preserves_structured_text_scaling_and_properties() -> None:
    hero = {
        "id": 7,
        "name": "Hero",
        "class_name": "hero_test",
        "description": {
            "lore": "<b>Lore</b>",
            "role": " Controls {target} space ",
            "playstyle": "Enable allies.",
        },
        "scaling_stats": {"spirit": {"coefficient": 1.25}},
        "level_info": [{"level": 1, "ability_points": 0}],
        "items": {f"signature{slot}": f"ability_{slot}" for slot in range(1, 5)},
    }
    assets = [
        {
            "id": slot,
            "class_name": f"ability_{slot}",
            "name": f"Ability {slot}",
            "type": "ability",
            "description": {"desc": "<i>Deals damage</i>"},
            "properties": {
                "damage": {
                    "value": 100,
                    "prefix": "+",
                    "scale_function": "linear",
                    "stat_coefficients": {"spirit": 0.7, "weapon": 0.2},
                    "condition": "charged",
                }
            },
        }
        for slot in range(1, 5)
    ]

    record = build_hero_mechanics(hero, assets)

    assert record["description"] == {
        "lore": "Lore",
        "playstyle": "Enable allies.",
        "role": "Controls space",
    }
    assert record["scaling_stats"] == hero["scaling_stats"]
    assert record["abilities"][0]["properties"]["damage"]["stat_coefficients"] == {
        "spirit": 0.7,
        "weapon": 0.2,
    }
    assert len(record["mechanics_sha256"]) == 64


def test_item_graph_handles_branches_cost_credit_and_component_consumption() -> None:
    graph = ItemGraph.from_assets([
        item(1, "component", cost=500),
        item(2, "first_child", cost=1250, components=["component"]),
        item(3, "second_child", cost=1500, components=["component"]),
    ])

    assert graph.children[1] == (2, 3)
    assert graph.transitive_components(2) == (1,)
    assert graph.incremental_cash_cost(2, (1,)) == 750
    assert graph.total_tree_investment(2) == 1250
    assert purchase_item(graph, InventoryState((1,)), 2).owned == (2,)


@pytest.mark.parametrize(
    "assets",
    [
        [item(1, "child", components=["missing"])],
        [
            item(1, "first", components=["second"]),
            item(2, "second", components=["first"]),
        ],
    ],
)
def test_item_graph_rejects_missing_references_and_cycles(
    assets: list[dict[str, Any]],
) -> None:
    with pytest.raises(MechanicsError):
        ItemGraph.from_assets(assets)


def test_category_bonus_boundaries_cross_once() -> None:
    table = CategoryBonusTable.from_asset({
        "cost_bonuses": {
            "weapon": [
                {"threshold": 800, "value": 1},
                {"threshold": 1600, "value": 2},
            ]
        }
    })

    assert not table.crossed("weapon", 0, 799)
    assert [bonus.threshold for bonus in table.crossed("weapon", 799, 1600)] == [
        800,
        1600,
    ]


def test_ability_timeline_uses_unlock_levels_and_asset_ap_grants() -> None:
    definitions = {
        10: AbilityDefinition(10, unlock_level=1),
        20: AbilityDefinition(20, unlock_level=3),
    }
    levels = {
        "1": {"bonus_currencies": ["EAbilityUnlocks"]},
        "2": {"bonus_currencies": ["EAbilityPoints"]},
        "3": {"bonus_currencies": ["EAbilityUnlocks"]},
        "4": {"ability_points": 2},
        "5": {"bonus_currencies": ["EAbilityPoints"]},
    }
    steps = validate_ability_timeline(
        definitions,
        levels,
        (
            AbilityAction(1, 10),
            AbilityAction(2, 10),
            AbilityAction(3, 20),
            AbilityAction(4, 10),
        ),
    )

    assert [(step.rank, step.cost, step.ap_remaining) for step in steps] == [
        (1, 1, 0),
        (2, 1, 0),
        (1, 1, 0),
        (3, 2, 0),
    ]
    with pytest.raises(MechanicsError, match="unlocks at level 3"):
        validate_ability_timeline(
            definitions,
            levels,
            (AbilityAction(1, 20),),
        )


def test_ability_definitions_preserve_asset_unlocks_costs_and_qualifiers() -> None:
    definitions = ability_definitions_from_kit({
        "abilities": [
            {
                "id": ability_id,
                "slot": slot,
                "unlock_level": 8 if slot == 4 else slot,
                "upgrade_costs": [1, 3, 6],
                "description": {"desc": "Channeled" if slot == 2 else "Basic"},
            }
            for slot, ability_id in enumerate((10, 20, 30, 40), start=1)
        ]
    })

    assert definitions[40].unlock_level == 8
    assert definitions[10].upgrade_costs == (1, 3, 6)
    assert definitions[20].qualifiers == frozenset({"channeled"})
    assert definitions[40].ultimate


def test_inventory_enforces_slots_actives_sells_and_flex() -> None:
    assets = [item(index, f"item_{index}", active=index <= 5) for index in range(1, 14)]
    graph = ItemGraph.from_assets(assets)
    state = InventoryState(unlocked_flex_slots=3)
    for item_id in range(1, 5):
        state = purchase_item(graph, state, item_id)
    with pytest.raises(MechanicsError, match="active-item"):
        purchase_item(graph, state, 5)
    with pytest.raises(MechanicsError, match="unowned"):
        sell_item(graph, state, 12)
    state = sell_item(graph, state, 4)
    assert state.owned == (1, 2, 3)
    with pytest.raises(MechanicsError, match="unavailable flex"):
        purchase_item(graph, InventoryState(), 6, required_flex_slots=1)


def test_imbue_requires_learned_qualified_allowed_ability() -> None:
    definitions = {
        10: AbilityDefinition(10, 1, qualifiers=frozenset({"charged"})),
        40: AbilityDefinition(40, 8, ultimate=True),
    }
    validate_imbue(
        definitions,
        {10},
        10,
        required_qualifier="charged",
        allow_ultimate=False,
    )
    with pytest.raises(MechanicsError, match="not proven channeled"):
        validate_imbue(
            definitions,
            {10},
            10,
            required_qualifier="channeled",
        )
    with pytest.raises(MechanicsError, match="ultimate"):
        validate_imbue(definitions, {40}, 40, allow_ultimate=False)


@pytest.mark.parametrize(
    ("description", "expected"),
    [
        ("Gain debuff immunity.", "hard_control"),
        ("Applies healing reduction.", "healing"),
        ("Gain bullet resist.", "bullet_pressure"),
        ("Gain spirit shield.", "spirit_burst"),
        ("Gain slow immunity.", "mobility_denial"),
        ("Shield an ally.", "ally_protection"),
    ],
)
def test_threat_classes_require_explicit_item_mechanics(
    description: str,
    expected: str,
) -> None:
    asset = item(99, "response")
    asset["description"] = {"desc": description}

    assert expected in classify_item_threat_responses(asset)


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
