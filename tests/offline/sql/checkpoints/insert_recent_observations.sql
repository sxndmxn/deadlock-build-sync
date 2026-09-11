INSERT INTO player_snapshots
SELECT
    match_id,
    player_slot,
    1700 AS stat_time,
    17000 AS net_worth
FROM player_matches;

INSERT INTO team_snapshots
SELECT
    p.match_id,
    t.team_id,
    1700 AS stat_time,
    102000 AS team_net_worth,
    6 AS observed_players
FROM player_matches AS p CROSS JOIN range(2) AS t (team_id);

UPDATE player_snapshots
SET net_worth = CASE WHEN match_id = 1 THEN NULL ELSE 0 END
WHERE match_id IN (1, 6) AND stat_time = 1799;

UPDATE team_snapshots
SET
    observed_players = CASE
        WHEN (match_id = 3 AND team_id = 0) OR (match_id = 4 AND team_id = 1) THEN 5
        ELSE 6
    END
WHERE stat_time = 1799;

INSERT INTO team_snapshots VALUES (7, 0, 1799, NULL, 6);
