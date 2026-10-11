SELECT
    item_id,
    item_name,
    class_name,
    tier,
    "cost",
    component_items_json
FROM item_assets
ORDER BY item_id;
