CREATE TABLE player_matches AS
SELECT
    t.i AS match_id,
    p.s AS player_slot,
    71 AS average_badge,
    to_timestamp(1000 + t.i * 100) AS start_time
FROM range(10) AS t (i) CROSS JOIN range(12) AS p (s);
