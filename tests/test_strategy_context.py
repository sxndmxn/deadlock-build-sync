from copy import deepcopy
from typing import Any

import pytest

from deadlock_build_sync.ability_order import AbilityPath
from deadlock_build_sync.api import Patch
from deadlock_build_sync.purchase_guide import (
    GuideItem,
    PurchaseGuide,
    PurchaseWindow,
)
from deadlock_build_sync.ranks import DEFAULT_RANK_RANGE
from deadlock_build_sync.strategy_context import (
    StrategyContextError,
    build_hero_strategy_context,
    build_strategy_context_document,
    calculate_context_sha256,
    calculate_kit_basis_sha256,
    calculate_narrative_basis_sha256,
    calculate_source_context_sha256,
    validate_strategy_context_document,
)


def test_exports_descriptions_slots_stats_and_quartered_ability_steps() -> None:
    window = PurchaseWindow(5000, 10000, 100, 60, 0.6, 0.5)
    item = GuideItem(101, "Rapid Recharge", 1, 200, 0.55, 0.48, 1.0, (window,))
    path = (10, 10, 20, 30, 10, 20, 40, 20, 30, 10, 20, 30, 30, 40, 40, 40)
    guide = PurchaseGuide(
        12,
        "Kelvin",
        "hero_kelvin",
        {1: (item,), 2: (), 3: (), 4: ()},
        ability_path=AbilityPath(path, 100, 60, 40, 250),
    )
    hero = {
        "id": 12,
        "name": "Kelvin",
        "description": "<b>Controls space</b> with ice.",
        "items": {
            "signature1": "ability_one",
            "signature2": "ability_two",
            "signature3": "ability_three",
            "signature4": "ability_four",
        },
    }
    assets: list[dict[str, Any]] = [
        {
            "id": ability_id,
            "name": name,
            "class_name": f"ability_{word}",
            "type": "ability",
            "ability_type": "signature",
            "description": {"desc": f"<span>{name}</span> description."},
            "properties": (
                {
                    "AbilityCharges": {
                        "value": 1,
                        "label": "Ability Charges",
                    }
                }
                if ability_id == 10
                else {}
            ),
        }
        for ability_id, name, word in (
            (10, "Grenade", "one"),
            (20, "Beam", "two"),
            (30, "Path", "three"),
            (40, "Shelter", "four"),
        )
    ]
    assets.append({
        "id": 101,
        "name": "Rapid Recharge",
        "type": "upgrade",
        "item_slot_type": "spirit",
        "is_active_item": False,
        "description": {"passive": "Adds another ability charge."},
        "properties": {
            "TechPower": {
                "value": 9,
                "label": "Spirit Power",
                "postfix": "",
                "tooltip_section": "innate",
            },
            "IgnoredZero": {
                "value": 0,
                "label": "Ignored",
                "tooltip_section": "innate",
            },
        },
    })

    context = build_hero_strategy_context(guide, hero, assets)
    assert context["hero_description"] == "Controls space with ice."
    assert context["abilities"][0]["description"]["desc"] == "Grenade description."
    assert context["abilities"][0]["stats"] == [
        {
            "property": "AbilityCharges",
            "label": "Ability Charges",
            "value": 1,
            "postfix": None,
        }
    ]
    assert context["tiers"]["I"][0]["slot"] == "SPIRIT"
    assert context["tiers"]["I"][0]["description"]["passive"] == (
        "Adds another ability charge."
    )
    assert context["tiers"]["I"][0]["stats"] == [
        {
            "property": "TechPower",
            "label": "Spirit Power",
            "value": 9,
            "postfix": None,
        }
    ]
    assert context["tiers"]["I"][0]["purchase_windows"][0]["label"] == "5–10k"
    assert context["ability_path"]["steps"][0] == {
        "position": 1,
        "quarter": 1,
        "ability_id": 10,
        "ability": "Grenade",
        "upgrade": "UNLOCK",
    }
    assert context["ability_path"]["steps"][4]["quarter"] == 2
    assert len(context["kit_basis_sha256"]) == 64
    assert len(context["narrative_basis_sha256"]) == 64
    assert len(context["context_sha256"]) == 64

    document = build_strategy_context_document(
        Patch("Patch", 123, "2026-01-01T00:00:00Z"),
        [context],
        DEFAULT_RANK_RANGE,
    )
    assert document["heroes"] == [context]
    assert document["filters"]["rank_range"] == DEFAULT_RANK_RANGE.as_dict()
    assert len(document["source_context_sha256"]) == 64
    assert context["narrative_basis_sha256"] == calculate_narrative_basis_sha256(
        context
    )
    assert context["kit_basis_sha256"] == calculate_kit_basis_sha256(context)
    assert context["context_sha256"] == calculate_context_sha256(context)
    assert document["source_context_sha256"] == calculate_source_context_sha256(
        document
    )
    validate_strategy_context_document(document)

    edited_hero = deepcopy(document)
    edited_hero["heroes"][0]["hero_description"] = "Edited after export."
    with pytest.raises(StrategyContextError, match="kit basis was edited"):
        validate_strategy_context_document(edited_hero)

    edited_patch = deepcopy(document)
    edited_patch["patch"]["title"] = "Edited patch"
    with pytest.raises(StrategyContextError, match="document was edited"):
        validate_strategy_context_document(edited_patch)


def test_narrative_basis_ignores_volatile_analytics() -> None:
    hero = {"id": 12, "name": "Kelvin", "class_name": "hero_kelvin"}
    assets = [
        {
            "id": 101,
            "name": "Rapid Recharge",
            "item_slot_type": "spirit",
            "description": {"passive": "Adds another ability charge."},
        }
    ]
    original_item = GuideItem(
        101,
        "Rapid Recharge",
        1,
        200,
        0.55,
        0.48,
        1.0,
        (PurchaseWindow(5000, 10000, 100, 60, 0.6, 0.5),),
    )
    advanced_item = GuideItem(
        101,
        "Rapid Recharge",
        1,
        400,
        0.56,
        0.51,
        1.0,
        (PurchaseWindow(5000, 10000, 200, 122, 0.61, 0.55),),
    )

    original = build_hero_strategy_context(
        PurchaseGuide(
            12, "Kelvin", "hero_kelvin", {1: (original_item,), 2: (), 3: (), 4: ()}
        ),
        hero,
        assets,
    )
    advanced = build_hero_strategy_context(
        PurchaseGuide(
            12, "Kelvin", "hero_kelvin", {1: (advanced_item,), 2: (), 3: (), 4: ()}
        ),
        hero,
        assets,
    )

    assert original["context_sha256"] != advanced["context_sha256"]
    assert original["kit_basis_sha256"] == advanced["kit_basis_sha256"]
    assert original["narrative_basis_sha256"] == advanced["narrative_basis_sha256"]

    shifted_window_item = GuideItem(
        101,
        "Rapid Recharge",
        1,
        200,
        0.55,
        0.48,
        1.0,
        (PurchaseWindow(6000, 11000, 100, 60, 0.6, 0.5),),
    )
    shifted = build_hero_strategy_context(
        PurchaseGuide(
            12,
            "Kelvin",
            "hero_kelvin",
            {1: (shifted_window_item,), 2: (), 3: (), 4: ()},
        ),
        hero,
        assets,
    )
    assert original["narrative_basis_sha256"] != shifted["narrative_basis_sha256"]
