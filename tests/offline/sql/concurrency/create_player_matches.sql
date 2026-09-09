CREATE TABLE player_matches AS
SELECT * FROM (VALUES (1, 1), (2, 2), (3, 3), (4, 4))
    AS matches(match_id, start_time);
