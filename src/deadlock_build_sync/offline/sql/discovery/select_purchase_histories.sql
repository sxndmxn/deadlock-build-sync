SELECT
    p.match_id,
    p.player_slot,
    p.item_id,
    p.buy_time,
    p.sold_time
FROM purchases AS p INNER JOIN discovery_partitions AS d ON p.match_id = d.match_id
WHERE p.hero_id = $hero AND p.buy_time < $ownership_before_seconds
ORDER BY p.match_id, p.player_slot, p.buy_time, p.event_order;
