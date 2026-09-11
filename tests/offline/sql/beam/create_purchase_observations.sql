CREATE TABLE discovery_partitions AS
SELECT
    t.i AS match_id,
    CASE
        WHEN t.i = 2 THEN 'selection' WHEN t.i = 3 THEN 'validation'
        WHEN t.i = 4 THEN 'test' ELSE 'discovery'
    END AS "partition"
FROM range(1, 12) AS t (i);

CREATE TABLE first_purchases AS
SELECT
    t.i AS match_id,
    6 AS hero_id,
    90 AS average_badge,
    0 AS team_id,
    1 AS item_id,
    TRUE AS won,
    CASE WHEN t.i = 5 THEN 2 ELSE 1 END AS same_second_purchase_count,
    CASE WHEN t.i = 6 THEN 2 ELSE 1 END AS item_purchase_ordinal,
    800 AS "cost",
    100 AS buy_time,
    1800 AS duration_s,
    CASE WHEN t.i = 7 THEN NULL ELSE 2400 END AS own_net_worth_at_buy,
    CASE WHEN t.i = 8 THEN 100 ELSE 90 END AS state_observed_at_s
FROM range(1, 12) AS t (i);

CREATE TABLE team_snapshots AS
SELECT
    t.i AS match_id,
    teams.team AS team_id,
    CASE WHEN t.i = 9 THEN 100 ELSE 90 END AS stat_time,
    14400 AS team_net_worth,
    CASE WHEN t.i = 10 THEN 5 ELSE 6 END AS observed_players
FROM range(1, 11) AS t (i) CROSS JOIN range(2) AS teams (team);

INSERT INTO team_snapshots VALUES (10, 0, 80, 14400, 6), (10, 1, 80, 14400, 6);
