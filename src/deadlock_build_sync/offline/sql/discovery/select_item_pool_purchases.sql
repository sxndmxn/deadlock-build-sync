SELECT p.match_id,p.player_slot,p.item_id,p.buy_time,
       p.own_net_worth_at_buy,p.state_observed_at_s
FROM purchases p JOIN _discovery_buyers b USING(match_id,player_slot)
WHERE p.buy_time<=p.duration_s
QUALIFY row_number() OVER (
    PARTITION BY p.match_id,p.player_slot,p.item_id
    ORDER BY p.buy_time,p.event_order
)=1;
