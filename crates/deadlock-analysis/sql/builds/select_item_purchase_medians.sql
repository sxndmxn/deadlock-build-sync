SELECT
    hero_id,
    item_id,
    median(buy_time)::DOUBLE AS median_buy_time_s,
    round(median(coalesce(own_net_worth_at_buy, 0)))::UINTEGER AS median_net_worth,
    round(quantile_cont(coalesce(own_net_worth_at_buy, 0), 0.25))::UINTEGER
        AS lower_quartile_net_worth,
    round(quantile_cont(coalesce(own_net_worth_at_buy, 0), 0.75))::UINTEGER
        AS upper_quartile_net_worth
FROM purchases
WHERE
    average_badge BETWEEN $minimum_badge AND $maximum_badge
    AND item_purchase_ordinal = 1
    AND NOT calibration
GROUP BY hero_id, item_id
ORDER BY hero_id, item_id;
