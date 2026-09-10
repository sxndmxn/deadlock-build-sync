INSERT INTO player_matches
SELECT
    match_id + 100 AS match_id,
    player_slot,
    61 AS average_badge,
    start_time
FROM player_matches;
