CREATE TABLE team_snapshots AS
WITH snapshots AS (
    SELECT
        p.match_id,
        CASE WHEN p.team = 'Team0' THEN 0 ELSE 1 END AS team_id,
        unnest(p."stats.time_stamp_s") AS stat_time,
        unnest(p."stats.net_worth") AS player_net_worth
    FROM remote."main".match_player AS p
    INNER JOIN eligible_matches AS e ON p.match_id = e.match_id
)

SELECT
    match_id,
    team_id,
    stat_time,
    sum(player_net_worth) AS team_net_worth,
    count(*) AS observed_players
FROM snapshots
GROUP BY match_id, team_id, stat_time;
