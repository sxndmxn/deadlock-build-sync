import pytest

from deadlock_build_sync.build_tags import (
    BuildTagCatalog,
    BuildTagError,
    select_build_tags,
)


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


def test_classifier_uses_stable_axis_tie_and_explicit_function() -> None:
    catalog = BuildTagCatalog.from_assets(tag_assets())
    assets = [
        {
            "id": 1,
            "cost": 500,
            "item_slot_type": "weapon",
            "description": "Applies anti-heal.",
        },
        {
            "id": 2,
            "cost": 500,
            "item_slot_type": "spirit",
            "description": "Applies anti-heal.",
        },
    ]

    selected = select_build_tags((1, 2), assets, catalog)

    assert selected.class_names == (
        "citadel_build_tag_weapon",
        "citadel_build_tag_debuff",
        "citadel_build_tag_complexity_2",
    )
    assert selected.archetype == "Debuff / Weapon"
    assert len(set(selected.tag_ids)) == 3
