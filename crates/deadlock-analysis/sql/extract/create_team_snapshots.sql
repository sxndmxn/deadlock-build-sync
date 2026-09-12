CREATE TABLE team_snapshots AS
WITH snapshots AS (
    SELECT
        p.match_id,
        p.player_slot,
        CASE WHEN p.team = 'Team0' THEN 0 ELSE 1 END AS team_id,
        unnest(p."stats.time_stamp_s") AS stat_time,
        unnest(p."stats.net_worth") AS player_net_worth,
        len(p."stats.time_stamp_s") = len(p."stats.net_worth")
            AS snapshot_arrays_aligned
    FROM remote."main".match_player AS p
    INNER JOIN eligible_matches AS e ON p.match_id = e.match_id
)

SELECT
    match_id,
    team_id,
    stat_time,
    CASE
        WHEN
            count(*) = 6 AND count(DISTINCT player_slot) = 6
            AND count(player_net_worth) = 6
            AND bool_and(snapshot_arrays_aligned IS TRUE)
            THEN sum(player_net_worth)
    END AS team_net_worth,
    count(DISTINCT player_slot) FILTER (
        WHERE snapshot_arrays_aligned AND player_net_worth IS NOT NULL
    ) AS observed_players
FROM snapshots
WHERE stat_time IS NOT NULL
GROUP BY match_id, team_id, stat_time;
