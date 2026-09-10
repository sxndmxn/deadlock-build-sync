CREATE TABLE player_matches AS SELECT
    t.i AS match_id,
    0 AS player_slot,
    7 AS hero_id,
    0 AS team_id,
    TRUE AS won,
    71 AS average_badge,
    1800 AS duration_s,
    to_timestamp(t.i) AS start_time
FROM range(100) AS t (i);
