SELECT DISTINCT count(*) FROM player_matches p
JOIN discovery_partitions d USING(match_id) GROUP BY match_id;
