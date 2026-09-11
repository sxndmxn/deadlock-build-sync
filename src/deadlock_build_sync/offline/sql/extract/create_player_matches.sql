CREATE TABLE player_matches AS
SELECT
    p.match_id,
    p.player_slot,
    CASE WHEN p.team = 'Team0' THEN 0 ELSE 1 END AS team_id,
    p.hero_id,
    p.assigned_lane,
    p.average_badge,
    p.won,
    p.start_time,
    p.duration_s,
    p.net_worth AS final_net_worth,
    coalesce(p.player_rank_initial_calibration_games, 0) > 0 AS calibration
FROM remote."main".match_player AS p
INNER JOIN eligible_matches AS e ON p.match_id = e.match_id
ORDER BY p.hero_id, p.match_id, p.player_slot;
