WITH hero_actors AS (
    SELECT DISTINCT match_id,player_slot,team_id FROM player_matches
    WHERE hero_id=$hero AND average_badge BETWEEN $minimum AND $maximum
)
SELECT p.match_id,p.player_slot,p.team_id,p.item_id,p.buy_time,
       coalesce(p.sold_time,0) AS sold_time
FROM purchases p JOIN discovery_partitions d USING(match_id)
JOIN hero_actors h ON p.match_id=h.match_id
  AND (p.player_slot=h.player_slot OR p.team_id!=h.team_id)
WHERE d.partition IN ('discovery','validation')
ORDER BY p.match_id,p.player_slot,p.buy_time,p.event_order;
