CREATE TABLE first_purchases AS SELECT
    match_id,
    player_slot,
    hero_id,
    item_id,
    item_name,
    tier,
    "cost",
    slot,
    active,
    fold,
    won,
    buy_time,
    duration_s,
    own_net_worth_at_buy,
    imbued_ability_id
FROM first_source;
