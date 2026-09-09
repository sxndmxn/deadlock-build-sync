CREATE TABLE player_matches AS
SELECT i AS match_id, s AS player_slot, 71 AS average_badge,
       to_timestamp(1000+i*100) AS start_time
FROM range(10) t(i) CROSS JOIN range(12) p(s);
