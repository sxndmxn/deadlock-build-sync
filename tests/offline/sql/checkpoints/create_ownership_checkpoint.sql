CREATE TABLE player_matches AS
SELECT
    actors.i AS match_id,
    0 AS player_slot,
    7 AS hero_id,
    0 AS team_id,
    TRUE AS won,
    90 AS average_badge,
    CASE WHEN actors.i = 2 THEN 1799 ELSE 2000 END AS duration_s,
    to_timestamp(actors.i) AS start_time
FROM range(1, 8) AS actors (i);

CREATE TABLE discovery_partitions AS
SELECT
    match_id,
    'discovery' AS "partition"
FROM player_matches;

CREATE TABLE compositions AS
SELECT
    match_id,
    1 AS team_id,
    [1, 2, 3, 4, 5, 6] AS hero_ids
FROM player_matches;

CREATE TABLE player_snapshots AS
SELECT
    match_id,
    player_slot,
    1199 AS stat_time,
    10000 AS net_worth
FROM player_matches
UNION ALL
SELECT
    match_id,
    player_slot,
    CASE WHEN match_id = 3 THEN 1500 WHEN match_id = 4 THEN 1499 ELSE 1799 END
        AS stat_time,
    18000 AS net_worth
FROM player_matches
WHERE match_id <> 7
UNION ALL
SELECT
    match_id,
    player_slot,
    1800 AS stat_time,
    99000 AS net_worth
FROM player_matches;

CREATE TABLE team_snapshots AS
SELECT
    p.match_id,
    t.team_id,
    1199 AS stat_time,
    60000 AS team_net_worth,
    6 AS observed_players
FROM player_matches AS p CROSS JOIN range(2) AS t (team_id)
UNION ALL
SELECT
    p.match_id,
    t.team_id,
    CASE WHEN p.match_id = 5 THEN 1499 ELSE 1799 END AS stat_time,
    108000 AS team_net_worth,
    CASE WHEN p.match_id = 6 THEN 5 ELSE 6 END AS observed_players
FROM player_matches AS p CROSS JOIN range(2) AS t (team_id)
WHERE p.match_id <> 7;

CREATE TABLE purchases AS
SELECT
    p.match_id,
    p.player_slot,
    p.hero_id,
    events.item_id,
    events.buy_time,
    events.sold_time,
    events.item_id AS event_order
FROM player_matches AS p
CROSS JOIN (
    VALUES (0, 1199, 0), (1, 1200, 0), (2, 1799, 0), (3, 1800, 0),
    (4, 100, 1799), (5, 100, 1800)
) AS events (item_id, buy_time, sold_time);
