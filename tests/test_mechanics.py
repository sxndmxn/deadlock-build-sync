import pytest

from deadlock_build_sync.mechanics import (
    AbilityAction,
    AbilityDefinition,
    CategoryBonusTable,
    InventoryState,
    ItemGraph,
    MechanicsError,
    build_hero_mechanics,
    classify_item_threat_responses,
    conditional_item_decision,
    parse_ability_definitions,
    purchase_item,
    schedule_component_path,
    sell_item,
    validate_ability_timeline,
    validate_imbue,
)
from deadlock_build_sync.value_validation import (
    require_object_dict,
    require_object_rows,
)
from tests.mechanics_fixtures import make_item_asset


def test_kit_record_preserves_structured_text_scaling_and_properties() -> None:
    hero: dict[str, object] = {
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
    assets: list[dict[str, object]] = [
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
    abilities = require_object_rows(record["abilities"])
    properties = require_object_dict(abilities[0]["properties"])
    damage = require_object_dict(properties["damage"])
    assert damage["stat_coefficients"] == {
        "spirit": 0.7,
        "weapon": 0.2,
    }
    mechanics_sha256 = record["mechanics_sha256"]
    assert isinstance(mechanics_sha256, str)
    assert len(mechanics_sha256) == 64


def test_item_graph_handles_branches_cost_credit_and_component_consumption() -> None:
    graph = ItemGraph.from_assets([
        make_item_asset(1, "component", cost=500),
        make_item_asset(2, "first_child", cost=1250, components=["component"]),
        make_item_asset(3, "second_child", cost=1500, components=["component"]),
    ])

    assert graph.children[1] == (2, 3)
    assert graph.transitive_components(2) == (1,)
    assert graph.incremental_cash_cost(2, (1,)) == 750
    assert graph.total_tree_investment(2) == 1250
    assert purchase_item(graph, InventoryState((1,)), 2).owned == (2,)


def test_component_schedule_moves_an_early_component_before_prior_core() -> None:
    graph = ItemGraph.from_assets([
        make_item_asset(1, "early_component"),
        make_item_asset(2, "first_core"),
        make_item_asset(3, "late_upgrade", components=["early_component"]),
    ])

    path = schedule_component_path(
        graph,
        (2, 3),
        {
            1: (6_000.0, 300.0, 1),
            2: (9_000.0, 500.0, 2),
            3: (19_000.0, 1_200.0, 3),
        },
    )

    assert path == (1, 2, 3)


def test_component_schedule_rebuys_only_after_the_first_copy_is_consumed() -> None:
    graph = ItemGraph.from_assets([
        make_item_asset(1, "shared_component"),
        make_item_asset(2, "first_upgrade", components=["shared_component"]),
        make_item_asset(3, "second_upgrade", components=["shared_component"]),
    ])

    path = schedule_component_path(
        graph,
        (2, 3),
        {
            1: (2_000.0, 100.0, 1),
            2: (8_000.0, 500.0, 2),
            3: (16_000.0, 1_000.0, 3),
        },
    )

    assert path == (1, 2, 1, 3)


@pytest.mark.parametrize(
    "assets",
    [
        [make_item_asset(1, "child", components=["missing"])],
        [
            make_item_asset(1, "first", components=["second"]),
            make_item_asset(2, "second", components=["first"]),
        ],
    ],
)
def test_item_graph_rejects_missing_references_and_cycles(
    assets: list[dict[str, object]],
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
    invalid_actions = (AbilityAction(1, 20),)
    with pytest.raises(MechanicsError, match="unlocks at level 3"):
        validate_ability_timeline(definitions, levels, invalid_actions)


def test_ability_definitions_preserve_asset_unlocks_costs_and_qualifiers() -> None:
    definitions = parse_ability_definitions({
        "abilities": [
            {
                "id": ability_id,
                "slot": slot,
                "unlock_level": 8 if slot == 4 else slot,
                "upgrade_costs": [1, 3, 6],
                "description": {"desc": "Channeled" if slot == 2 else "Basic"},
                **(
                    {
                        "properties": {
                            "AbilityChannelTime": {
                                "value": "2.5",
                                "disable_value": "0",
                            }
                        }
                    }
                    if slot == 3
                    else {}
                ),
            }
            for slot, ability_id in enumerate((10, 20, 30, 40), start=1)
        ]
    })

    assert definitions[40].unlock_level == 8
    assert definitions[10].upgrade_costs == (1, 3, 6)
    assert definitions[20].qualifiers == frozenset({"channeled"})
    assert definitions[30].qualifiers == frozenset({"channeled"})
    assert definitions[40].ultimate


def test_inventory_enforces_slots_actives_sells_and_flex() -> None:
    assets = [
        make_item_asset(index, f"item_{index}", active=index <= 5)
        for index in range(1, 14)
    ]
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
    empty_state = InventoryState()
    with pytest.raises(MechanicsError, match="unavailable flex"):
        purchase_item(graph, empty_state, 6, required_flex_slots=1)


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
        ("Gain slow immunity.", "slow_resistance"),
        ("Shield an ally.", "ally_protection"),
    ],
)
def test_threat_classes_require_explicit_item_mechanics(
    description: str,
    expected: str,
) -> None:
    asset = make_item_asset(99, "response")
    asset["description"] = {"desc": description}

    assert expected in classify_item_threat_responses(asset)


def test_scourge_decision_uses_both_item_mechanics() -> None:
    scourge = make_item_asset(1, "scourge")
    scourge["description"] = {
        "desc": (
            "Apply Spirit Resist, Debuff Resist and an aura on a friendly target. "
            "Can be self cast."
        )
    }
    phantom = make_item_asset(2, "phantom_strike")
    phantom["description"] = {
        "desc": "Teleport to an enemy, then ground, slow, and disarm them."
    }

    assert conditional_item_decision(scourge, phantom) == (
        "Heavy Spirit damage",
        "Spirit Resist and Debuff Resist for self/ally",
        "Before the next Spirit-heavy fight",
        "Keep default when catch matters more",
    )


def test_reverse_decision_keeps_scourge_when_survival_matters_more() -> None:
    phantom = make_item_asset(2, "phantom_strike")
    phantom["description"] = {
        "desc": "Teleport to an enemy, then ground, slow, and disarm them."
    }
    scourge = make_item_asset(1, "scourge")
    scourge["description"] = {
        "desc": "Apply Spirit Resist and Debuff Resist to a friendly target."
    }

    assert conditional_item_decision(phantom, scourge) == (
        "Enemy escape or mobility",
        "Ground and Disarm",
        "Before fighting an evasive target",
        "Keep default when survival matters more",
    )
    assert classify_item_threat_responses(phantom) == frozenset({"mobility_denial"})


def test_unstoppable_immunity_is_control_defense_and_protects_singularity() -> None:
    unstoppable = make_item_asset(3357231760, "upgrade_unstoppable", active=True)
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
    weapon = make_item_asset(100, "weapon_item")
    weapon["description"] = {"desc": "Gain Weapon Damage."}
    assert classify_item_threat_responses(unstoppable) == frozenset({"hard_control"})
    assert conditional_item_decision(unstoppable, weapon) == (
        "Hard control or debuffs",
        "Control Immunity",
        "Before entering the next control-heavy fight",
        "Keep default when weapon pressure matters more",
    )
