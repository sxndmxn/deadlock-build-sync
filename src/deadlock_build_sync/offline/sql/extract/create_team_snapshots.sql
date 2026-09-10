CREATE TABLE team_snapshots AS
WITH snapshots AS (
    SELECT
        match_id,
        CASE WHEN team = 'Team0' THEN 0 ELSE 1 END AS team_id,
        unnest("stats.time_stamp_s") AS stat_time,
        unnest("stats.net_worth") AS player_net_worth
    FROM remote.main.match_player
    INNER JOIN eligible_matches USING (match_id)
)
SELECT match_id, team_id, stat_time,
       sum(player_net_worth) AS team_net_worth,
       count(*) AS observed_players
FROM snapshots
GROUP BY match_id, team_id, stat_time;
