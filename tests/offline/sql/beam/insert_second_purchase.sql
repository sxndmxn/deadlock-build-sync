INSERT INTO first_purchases
SELECT
    match_id,
    hero_id,
    average_badge,
    team_id,
    2 AS item_id,
    won,
    same_second_purchase_count,
    item_purchase_ordinal,
    "cost",
    110 AS buy_time,
    duration_s,
    own_net_worth_at_buy,
    state_observed_at_s
FROM first_purchases
WHERE match_id = 1;
