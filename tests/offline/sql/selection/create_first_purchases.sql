CREATE TABLE first_purchases AS SELECT
    actors.i AS match_id,
    0 AS player_slot,
    7 AS hero_id,
    items.j AS item_id,
    'Item' AS item_name,
    1 AS tier,
    500 AS "cost",
    'weapon' AS slot,
    FALSE AS active,
    CASE
        WHEN actors.i <= 25 THEN 'train' WHEN actors.i <= 50 THEN 'validation'
        ELSE 'test'
    END AS fold,
    actors.i % 2 = 0 AS won,
    600 + items.j AS buy_time,
    1800 AS duration_s,
    10000 + items.j AS own_net_worth_at_buy,
    CASE WHEN actors.i <= 15 OR actors.i BETWEEN 26 AND 40 THEN 40 ELSE 41 END
        AS imbued_ability_id
FROM range(1, 71) AS actors (i) CROSS JOIN range(1, 8) AS items (j)
WHERE
    items.j NOT IN (2, 3, 4)
    OR (actors.i <= 52 - items.j)
    OR (items.j = 4 AND actors.i > 50);
