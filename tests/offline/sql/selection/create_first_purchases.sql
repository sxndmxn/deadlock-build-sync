CREATE TABLE first_purchases AS SELECT
    i AS match_id, 0 AS player_slot, 7 AS hero_id, j AS item_id,
    'Item' AS item_name, 1 AS tier, 500 AS cost, 'weapon' AS slot,
    false AS active,
    CASE WHEN i<=25 THEN 'train' WHEN i<=50 THEN 'validation'
         ELSE 'test' END AS fold,
    i%2=0 AS won, 600+j AS buy_time, 1800 AS duration_s,
    10000+j AS own_net_worth_at_buy,
    CASE WHEN i<=15 OR i BETWEEN 26 AND 40 THEN 40 ELSE 41 END
        AS imbued_ability_id
FROM range(1,71) actors(i) CROSS JOIN range(1,8) items(j)
WHERE j NOT IN (2,3,4) OR (i <= 52-j) OR (j=4 AND i>50);
