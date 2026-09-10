SELECT
    p.match_id,
    p.player_slot,
    p.item_id,
    p.buy_time,
    p.sold_time
FROM purchases AS p INNER JOIN match_folds AS f ON p.match_id = f.match_id
WHERE f.fold = $partition AND p.hero_id = $hero
ORDER BY p.match_id, p.player_slot, p.buy_time, p.event_order;
