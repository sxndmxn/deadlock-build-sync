SELECT
    p.match_id,
    p.player_slot,
    p.item_id,
    p.buy_time,
    p.own_net_worth_at_buy,
    p.state_observed_at_s
FROM purchases AS p
INNER JOIN
    _discovery_buyers AS b
    ON p.match_id = b.match_id AND p.player_slot = b.player_slot
WHERE p.buy_time <= p.duration_s
QUALIFY row_number() OVER (
    PARTITION BY p.match_id, p.player_slot, p.item_id
    ORDER BY p.buy_time, p.event_order
) = 1;
