import pytest

from deadlock_build_sync.mechanics import (
    AbilityAction,
    AbilityDefinition,
    CategoryBonusTable,
    InventoryState,
    ItemGraph,
    MechanicsError,
    build_hero_mechanics,
    parse_ability_definitions,
    purchase_item,
    schedule_ability_path,
    schedule_component_path,
    validate_ability_timeline,
    validate_imbue,
)
from deadlock_build_sync.mechanics_assets import (
    clean_mechanical_text,
    extract_asset_mechanics,
    normalize_hero_description,
    normalize_mechanical_value,
)
from deadlock_build_sync.mechanics_compatibility import (
    asset_mechanics_refs,
    hero_item_affinity_scores,
)
from tests.mechanics_fixtures import make_item_asset


def _ability_rows() -> list[dict[str, object]]:
    return [
        {
            "id": ability_id,
            "slot": slot,
            "description": {"desc": "Basic"},
        }
        for slot, ability_id in enumerate((10, 20, 30, 40), start=1)
    ]


@pytest.mark.parametrize(
    "abilities",
    [None, [], [{"id": 10}], [*(_ability_rows()[:3]), {"id": "bad"}]],
)
def test_ability_definitions_reject_incomplete_or_invalid_kits(
    abilities: object,
) -> None:
    with pytest.raises(MechanicsError):
        parse_ability_definitions({"abilities": abilities})


def test_ability_definitions_use_safe_defaults_for_bad_optional_fields() -> None:
    rows = _ability_rows()
    rows[0]["unlock_level"] = 0
    rows[0]["upgrade_costs"] = []
    rows[1]["upgrade_costs"] = [1, -1]
    rows[2]["upgrade_costs"] = "1,2,5"

    definitions = parse_ability_definitions({"abilities": rows})

    assert definitions[10].unlock_level == 1
    assert definitions[10].upgrade_costs == (1, 2, 5)
    assert definitions[20].upgrade_costs == (1, 2, 5)
    assert definitions[30].upgrade_costs == (1, 2, 5)


@pytest.mark.parametrize(
    "level_info",
    [
        None,
        [7],
        [{"level": "bad"}],
        [{"level": 1, "bonus_currencies": "EAbilityUnlocks"}],
        [{"level": 1, "bonus_currencies": [1]}],
        [{"level": 1, "ability_points": -1}],
        [{"level": 1, "ability_unlocks": -1}],
        [],
    ],
)
def test_ability_timeline_rejects_malformed_level_data(level_info: object) -> None:
    with pytest.raises(MechanicsError):
        validate_ability_timeline({10: AbilityDefinition(10, 1)}, level_info, ())


def test_ability_timeline_accepts_list_rows_and_explicit_grants() -> None:
    steps = validate_ability_timeline(
        {10: AbilityDefinition(10, 1)},
        [
            {"level": 1, "ability_unlocks": 1},
            {"level": 2, "ability_points_granted": 1},
        ],
        (AbilityAction(1, 10), AbilityAction(2, 10)),
    )

    assert [step.currency for step in steps] == ["ability_unlock", "ability_points"]


@pytest.mark.parametrize(
    ("definitions", "actions", "message"),
    [
        ({10: AbilityDefinition(10, 1)}, (AbilityAction(1, 99),), "unknown ability"),
        (
            {10: AbilityDefinition(10, 1)},
            (AbilityAction(2, 10), AbilityAction(1, 10)),
            "ordered by level",
        ),
        (
            {10: AbilityDefinition(10, 1)},
            (AbilityAction(3, 10),),
            "unknown level",
        ),
    ],
)
def test_ability_timeline_rejects_invalid_actions(
    definitions: dict[int, AbilityDefinition],
    actions: tuple[AbilityAction, ...],
    message: str,
) -> None:
    levels = {
        1: {"ability_unlocks": 1},
        2: {"ability_points": 10},
    }

    with pytest.raises(MechanicsError, match=message):
        validate_ability_timeline(definitions, levels, actions)


def test_ability_timeline_rejects_maxed_ability() -> None:
    with pytest.raises(MechanicsError, match="already maxed"):
        validate_ability_timeline(
            {10: AbilityDefinition(10, 1, upgrade_costs=(1,))},
            {
                1: {"ability_unlocks": 1},
                2: {"ability_points": 1},
                3: {"ability_points": 1},
            },
            (AbilityAction(1, 10), AbilityAction(2, 10), AbilityAction(3, 10)),
        )


def test_ability_schedule_reports_an_impossible_path() -> None:
    with pytest.raises(MechanicsError, match="cannot legally schedule"):
        schedule_ability_path(
            {10: AbilityDefinition(10, 1)},
            {1: {"ability_unlocks": 1}},
            (10, 10),
        )


def test_mechanics_value_normalization_handles_all_supported_shapes() -> None:
    assert not clean_mechanical_text(7)
    assert normalize_mechanical_value((" <b>one</b> ", "")) == ["one", ""]
    assert normalize_mechanical_value({2: None, 1: [" x "]}) == {"1": ["x"]}
    assert normalize_hero_description(" <i>Role</i> ") == {"summary": "Role"}
    assert normalize_hero_description("{token}") == {}
    assert normalize_hero_description(7) == {}


def test_asset_extraction_and_hero_build_reject_missing_identity() -> None:
    with pytest.raises(MechanicsError, match="numeric id"):
        extract_asset_mechanics({"id": "bad"})
    with pytest.raises(MechanicsError, match="numeric id"):
        build_hero_mechanics({}, [])


def test_hero_build_rejects_missing_signature_data() -> None:
    with pytest.raises(MechanicsError, match="no signature ability mapping"):
        build_hero_mechanics({"id": 7}, [])

    with pytest.raises(MechanicsError, match="missing signature ability 1"):
        build_hero_mechanics({"id": 7, "items": {"signature1": 5}}, [])


def test_asset_mechanics_refs_include_present_optional_sources() -> None:
    assert asset_mechanics_refs({"id": 7}) == ("asset:item:7",)
    assert asset_mechanics_refs({
        "id": 7,
        "description": {"desc": "Text"},
        "component_items": ["base"],
    }) == (
        "asset:item:7",
        "asset:item:7:description",
        "asset:item:7:components",
    )


def test_affinity_scores_require_a_hero_mapping_and_numeric_items() -> None:
    assert hero_item_affinity_scores({}, []) == {}

    hero: dict[str, object] = {"items": {"signature1": "ability", "signature2": 7}}
    assets: list[dict[str, object]] = [
        {"id": 1, "class_name": "ability", "description": "Heavy melee damage"},
        {"id": 2, "class_name": "item", "description": "Heavy melee attack"},
        {"id": "bad", "class_name": "bad", "description": "Heavy melee attack"},
        {"id": 3, "class_name": 3, "description": "Spirit damage"},
    ]

    assert hero_item_affinity_scores(hero, assets) == {1: 3, 2: 3}


def test_item_graph_rejects_empty_duplicate_and_malformed_assets() -> None:
    with pytest.raises(MechanicsError, match="empty"):
        ItemGraph.from_assets([])

    with pytest.raises(MechanicsError, match="class names must be unique"):
        ItemGraph.from_assets([make_item_asset(1, "same"), make_item_asset(2, "same")])

    malformed = make_item_asset(1, "bad")
    malformed["component_items"] = [7]
    with pytest.raises(MechanicsError, match="malformed components"):
        ItemGraph.from_assets([malformed])


def test_item_graph_skips_unavailable_assets_and_handles_shared_ancestors() -> None:
    disabled = make_item_asset(99, "disabled")
    disabled["disabled"] = True
    unshopable = make_item_asset(98, "unshopable")
    unshopable["shopable"] = False
    graph = ItemGraph.from_assets([
        disabled,
        unshopable,
        make_item_asset(1, "base"),
        make_item_asset(2, "left", components=["base"]),
        make_item_asset(3, "right", components=["base"]),
        make_item_asset(4, "top", components=["left", "right"]),
    ])

    assert graph.transitive_components(4) == (1, 2, 3)
    separate = ItemGraph.from_assets([
        make_item_asset(1, "base"),
        make_item_asset(4, "top", components=["base"]),
    ])
    for _ in range(2):
        assert separate.transitive_components(4) == (1,)
        assert graph.transitive_components(4) == (1, 2, 3)
    with pytest.raises(MechanicsError, match="unknown current item"):
        graph.require(99)
    with pytest.raises(MechanicsError, match="unknown current item"):
        graph.transitive_components(99)


def test_category_bonus_table_accepts_object_rows_and_validates_boundaries() -> None:
    table = CategoryBonusTable.from_asset({
        "cost_bonuses": {"Weapon": {"800": {"damage": 2}}}
    })

    assert table.categories["weapon"][0].threshold == 800
    assert table.categories["weapon"][0].values == {"value": {"damage": 2}}
    with pytest.raises(MechanicsError, match="move backwards"):
        table.crossed("weapon", 900, 800)


@pytest.mark.parametrize(
    ("cost_bonuses", "message"),
    [
        (None, "missing"),
        ({"weapon": "bad"}, "malformed"),
        ({"weapon": [7]}, "malformed"),
        ({"weapon": [{"threshold": -1}]}, "invalid"),
        (
            {"weapon": [{"threshold": 1}, {"gold_threshold": 1}]},
            "duplicate",
        ),
    ],
)
def test_category_bonus_table_rejects_bad_rows(
    cost_bonuses: object,
    message: str,
) -> None:
    with pytest.raises(MechanicsError, match=message):
        CategoryBonusTable.from_asset({"cost_bonuses": cost_bonuses})


def test_inventory_rejects_invalid_flex_and_ownership_limits() -> None:
    with pytest.raises(MechanicsError, match="between zero and three"):
        InventoryState(unlocked_flex_slots=4)

    unique_graph = ItemGraph.from_assets([make_item_asset(1, "unique")])
    with pytest.raises(MechanicsError, match="ownership limit"):
        purchase_item(unique_graph, InventoryState((1,)), 1)

    repeatable = make_item_asset(2, "repeatable")
    repeatable["is_unique"] = False
    repeatable["max_count"] = 2
    repeatable_graph = ItemGraph.from_assets([repeatable])
    with pytest.raises(MechanicsError, match="ownership limit"):
        purchase_item(repeatable_graph, InventoryState((2, 2)), 2)


def test_inventory_rejects_a_purchase_beyond_base_capacity() -> None:
    graph = ItemGraph.from_assets([
        make_item_asset(index, f"item_{index}") for index in range(10)
    ])
    state = InventoryState(tuple(range(9)))

    with pytest.raises(MechanicsError, match="available item slots"):
        purchase_item(graph, state, 9)


def test_component_schedule_rejects_empty_duplicate_and_impossible_targets() -> None:
    graph = ItemGraph.from_assets([make_item_asset(1, "one")])
    with pytest.raises(MechanicsError, match="no final inventory"):
        schedule_component_path(graph, (), {})
    with pytest.raises(MechanicsError, match="contains duplicates"):
        schedule_component_path(graph, (1, 1), {})

    active_assets = [
        make_item_asset(index, f"active_{index}", active=True) for index in range(5)
    ]
    active_graph = ItemGraph.from_assets(active_assets)
    with pytest.raises(MechanicsError, match="four active-item bindings"):
        schedule_component_path(active_graph, tuple(range(5)), {})


def test_validate_imbue_rejects_an_unknown_or_unlearned_ability() -> None:
    with pytest.raises(MechanicsError, match="current learned ability"):
        validate_imbue({10: AbilityDefinition(10, 1)}, set(), 10)
