import pytest

from deadlock_build_sync.build_tags import (
    BuildTagCatalog,
    BuildTagError,
    select_build_tags,
)
from deadlock_build_sync.purchase_guide import GuideItem
from deadlock_build_sync.value_validation import require_object_rows


def tag_assets() -> list[dict[str, object]]:
    classes = (
        "complexity_1",
        "complexity_2",
        "complexity_3",
        "crowd_control",
        "damage",
        "debuff",
        "headshots",
        "healing",
        "melee",
        "mobility",
        "spirit",
        "utility",
        "vitality",
        "weapon",
    )
    return [
        {
            "class_name": f"citadel_build_tag_{class_name}",
            "label": class_name.replace("_", " ").title(),
            "id": index,
        }
        for index, class_name in enumerate(classes, start=1)
    ]


def test_catalog_requires_exact_pinned_taxonomy_and_unique_ids() -> None:
    catalog = BuildTagCatalog.from_assets(tag_assets())

    assert len(catalog.tags) == 14
    assert len(catalog.sha256) == 64

    duplicate = tag_assets()
    duplicate[-1]["id"] = duplicate[0]["id"]
    with pytest.raises(BuildTagError, match="duplicate IDs"):
        BuildTagCatalog.from_assets(duplicate)


def guide_item(
    item_id: int,
    *,
    tier: int,
    win_rate: float,
    adopter_matches: int = 100,
    purchase_events: int = 120,
) -> GuideItem:
    return GuideItem(
        item_id=item_id,
        name=f"Item {item_id}",
        tier=tier,
        purchase_event_observations=purchase_events,
        observed_outcome_rate=win_rate,
        observed_outcome_lower_bound=0.0,
        relative_purchase_event_volume=1.0,
        windows=(),
        adopter_matches=adopter_matches,
        purchase_events=purchase_events,
    )


def test_selects_first_maxed_ability_best_tier_three_core_and_function() -> None:
    catalog = BuildTagCatalog.from_assets(tag_assets())
    assets: list[dict[str, object]] = [
        {
            "id": 1,
            "name": "Tier 3 Weapon",
            "class_name": "item_tier_3_weapon",
            "cost": 500,
            "item_slot_type": "weapon",
            "description": "Applies anti-heal.",
        },
        {
            "id": 2,
            "name": "Tier 3 Spirit",
            "class_name": "item_tier_3_spirit",
            "cost": 500,
            "item_slot_type": "spirit",
            "description": "Applies anti-heal.",
        },
        {
            "id": 3,
            "name": "Tier 4 Spirit",
            "class_name": "item_tier_4_spirit",
            "cost": 500,
            "item_slot_type": "spirit",
            "description": "Applies anti-heal.",
        },
    ]
    assets.extend(
        require_object_rows([
            {
                "id": ability_id,
                "name": f"Ability {ability_id}",
                "class_name": f"ability_{ability_id}",
                "type": "ability",
            }
            for ability_id in (10, 20, 30, 40)
        ])
    )
    ability_path = (*((10, 20, 30, 40) * 3), 20, 10, 30, 40)

    selected = select_build_tags(
        ability_path,
        (
            guide_item(1, tier=3, win_rate=0.52),
            guide_item(2, tier=3, win_rate=0.61),
            guide_item(3, tier=4, win_rate=0.90),
        ),
        assets,
        catalog,
    )

    assert selected.class_names == (
        "ability_20",
        "item_tier_3_spirit",
        "citadel_build_tag_debuff",
    )
    assert selected.labels == ("Ability 20", "Tier 3 Spirit", "Debuff")
    assert selected.tag_ids[:2] == (20, 2)
    assert selected.archetype == "Debuff / Spirit"
    assert len(set(selected.tag_ids)) == 3


def test_core_icon_falls_back_to_best_tier_four_item() -> None:
    catalog = BuildTagCatalog.from_assets(tag_assets())
    assets: list[dict[str, object]] = [
        {
            "id": item_id,
            "name": f"Item {item_id}",
            "class_name": f"item_{item_id}",
            "cost": tier * 500,
            "item_slot_type": "spirit",
        }
        for item_id, tier in ((1, 2), (2, 4), (3, 4))
    ] + [
        {
            "id": ability_id,
            "name": f"Ability {ability_id}",
            "class_name": f"ability_{ability_id}",
            "type": "ability",
        }
        for ability_id in (10, 20, 30, 40)
    ]

    selected = select_build_tags(
        (10, 20, 30, 40) * 4,
        (
            guide_item(1, tier=2, win_rate=0.99),
            guide_item(2, tier=4, win_rate=0.52),
            guide_item(3, tier=4, win_rate=0.61),
        ),
        assets,
        catalog,
    )

    assert selected.tag_ids[:2] == (10, 3)


def test_rejects_incomplete_ability_path_and_core_without_late_tier() -> None:
    catalog = BuildTagCatalog.from_assets(tag_assets())
    assets: list[dict[str, object]] = [
        {
            "id": 1,
            "name": "Item 1",
            "class_name": "item_1",
            "cost": 500,
            "item_slot_type": "weapon",
        },
    ]
    assets.extend(
        require_object_rows([
            {
                "id": ability_id,
                "name": f"Ability {ability_id}",
                "class_name": f"ability_{ability_id}",
            }
            for ability_id in (10, 20, 30, 40)
        ])
    )
    core = (guide_item(1, tier=2, win_rate=0.50),)

    with pytest.raises(BuildTagError, match="complete four-ability"):
        select_build_tags((10, 20, 30, 40), core, assets, catalog)
    with pytest.raises(BuildTagError, match="no Tier 3 or Tier 4"):
        select_build_tags((10, 20, 30, 40) * 4, core, assets, catalog)
