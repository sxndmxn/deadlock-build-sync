CREATE OR REPLACE TEMP TABLE _item_pool_purchases AS
SELECT
    p.match_id,
    p.player_slot,
    p.item_id,
    CASE
        WHEN p.buy_time >= 0 THEN p.buy_time::DOUBLE
        ELSE error('Purchase time must be nonnegative')
    END AS buy_time,
    CASE
        WHEN p.own_net_worth_at_buy IS NOT NULL AND NOT isfinite(p.own_net_worth_at_buy)
            THEN error('Quantile sample contains a nonfinite value')
        WHEN p.buy_time - p.state_observed_at_s BETWEEN 1 AND 300
            THEN p.own_net_worth_at_buy
    END AS fresh_wealth
FROM first_purchases AS p
INNER JOIN _discovery_buyers AS b
    ON p.match_id = b.match_id AND p.player_slot = b.player_slot
WHERE p.hero_id = $hero AND p.buy_time <= p.duration_s;
