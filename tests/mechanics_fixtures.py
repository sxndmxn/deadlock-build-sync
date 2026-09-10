def make_item_asset(
    item_id: int,
    class_name: str,
    *,
    cost: int = 500,
    components: list[str] | None = None,
    active: bool = False,
) -> dict[str, object]:
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
