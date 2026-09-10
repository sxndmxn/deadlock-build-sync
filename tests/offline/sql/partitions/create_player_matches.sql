CREATE TABLE player_matches AS
SELECT
    t.i // 2 AS match_id,
    t.i % 2 AS hero_id,
    t.i // 2 AS start_time
FROM range(20) AS t (i);
