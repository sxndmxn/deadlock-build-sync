CREATE TABLE item_assets (
    item_id UBIGINT,
    item_name VARCHAR,
    class_name VARCHAR,
    tier INTEGER,
    cost INTEGER,
    slot VARCHAR,
    active BOOLEAN,
    unique_item BOOLEAN,
    component_items_json VARCHAR
);
