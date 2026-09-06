from tests.build_evidence_fixtures import _fixture_card


def _projection() -> dict[str, object]:
    rows: list[dict[str, object]] = []
    for row_index, (name, count) in enumerate((
        ("CORE ITEMS", 6),
        ("TIER 1", 10),
        ("TIER 2", 10),
        ("TIER 3", 10),
        ("TIER 4", 10),
    )):
        start = 1001 if row_index == 0 else 2000 + row_index * 100
        columns = 6 if name == "CORE ITEMS" else 10 if name == "TIER 4" else 5
        width = {
            "CORE ITEMS": 567.0,
            "TIER 1": 465.75,
            "TIER 2": 562.5,
            "TIER 3": 465.75,
            "TIER 4": 1039.5,
        }[name]
        rows.append({
            "name": name,
            "optional": row_index > 0,
            "width": width,
            "height": 164.0 + 155.5 * ((count - 1) // columns),
            "items": [
                {
                    "item_id": start + offset,
                    "item": f"Item {start + offset}",
                    "annotation": _fixture_card(
                        (offset // 2) + 1 if row_index == 0 else row_index,
                        offset,
                    ),
                    "required_flex_slots": None,
                    "sell_priority": None,
                    "imbue_target_ability_id": None,
                }
                for offset in range(count)
            ],
        })
    return {
        "build": {
            "archetype": "Weapon Damage",
            "tag_ids": [10, 1005, 3],
            "tag_classes": [
                "ability_10",
                "item_1005",
                "citadel_build_tag_damage",
            ],
            "tag_labels": ["Ability 10", "Item 1005", "Damage"],
            "tag_catalog_sha256": "b" * 64,
        },
        "categories": rows,
        "semantics": "CORE only; tiers are optional.",
    }
