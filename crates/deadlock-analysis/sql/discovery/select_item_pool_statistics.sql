SELECT
    item_id,
    CASE
        WHEN
            count(*)
            = count(
                DISTINCT struct_pack(match_id := match_id, player_slot := player_slot)
            )
            THEN count(*)
        ELSE error('First-purchase evidence contains a duplicate player and item')
    END AS buyers,
    count(*)::DOUBLE / $population::DOUBLE AS adoption,
    quantile_cont(buy_time, [0.25, 0.5, 0.75]) AS time_seconds_q25_q50_q75,
    count(fresh_wealth) AS fresh_wealth_observations,
    quantile_cont(fresh_wealth, [0.25, 0.5, 0.75]) AS net_worth_q25_q50_q75
FROM _item_pool_purchases
GROUP BY item_id
ORDER BY item_id;
