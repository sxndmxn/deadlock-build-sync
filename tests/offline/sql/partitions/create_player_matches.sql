CREATE TABLE player_matches AS SELECT i//2 AS match_id, i%2 AS hero_id, i//2 AS start_time FROM range(20) t(i);
