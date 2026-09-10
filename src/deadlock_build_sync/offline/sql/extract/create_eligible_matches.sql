CREATE TABLE eligible_matches AS
SELECT match_id
FROM remote.main.match_player
WHERE match_mode = $match_mode
    AND game_mode = $game_mode
    AND start_time >= $since::TIMESTAMPTZ
    AND start_time + duration_s * INTERVAL '1 second' <= $as_of::TIMESTAMPTZ
    AND average_badge BETWEEN $minimum_badge AND $maximum_badge
GROUP BY match_id
HAVING count(*) = 12
    AND count(DISTINCT player_slot) = 12
    AND count(*) FILTER (WHERE team = 'Team0') = 6
    AND count(*) FILTER (WHERE team = 'Team1') = 6
    AND bool_and(rewards_eligible)
    AND bool_and(player_match_outcome IN ('Win', 'Loss'))
    AND count(*) FILTER (WHERE player_match_outcome = 'Win') = 6
    AND count(*) FILTER (WHERE player_match_outcome = 'Loss') = 6;
