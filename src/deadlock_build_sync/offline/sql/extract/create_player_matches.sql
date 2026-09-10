CREATE TABLE player_matches AS
SELECT
    match_id,
    player_slot,
    CASE WHEN team = 'Team0' THEN 0 ELSE 1 END AS team_id,
    hero_id,
    assigned_lane,
    average_badge,
    won,
    start_time,
    duration_s,
    net_worth AS final_net_worth,
    coalesce(player_rank_initial_calibration_games, 0) > 0 AS calibration
FROM remote.main.match_player
INNER JOIN eligible_matches USING (match_id)
ORDER BY hero_id, match_id, player_slot;
