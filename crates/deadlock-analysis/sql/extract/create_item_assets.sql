CREATE OR REPLACE TABLE item_assets (
    item_id UBIGINT,
    item_name VARCHAR,
    class_name VARCHAR,
    tier INTEGER,
    "cost" INTEGER,
    component_items_json VARCHAR
);
