SELECT p.match_id,p.player_slot,p.item_id,p.buy_time,p.sold_time
FROM purchases p JOIN discovery_partitions d USING(match_id)
WHERE p.hero_id=$hero AND p.buy_time<1200
ORDER BY p.match_id,p.player_slot,p.buy_time,p.event_order;
