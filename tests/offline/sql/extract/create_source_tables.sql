ATTACH ':memory:' AS remote;
CREATE TABLE source_snapshot AS SELECT 7::BIGINT AS version;
CREATE TABLE remote.main.match_player AS
SELECT
    match_number AS match_id,
    slot AS player_slot,
    CASE WHEN slot < 6 THEN 'Team0' ELSE 'Team1' END AS team,
    CASE WHEN slot < 6 THEN 'Win' ELSE 'Loss' END AS player_match_outcome,
    true AS rewards_eligible,
    'Ranked' AS match_mode,
    'Normal' AS game_mode,
    TIMESTAMPTZ '2026-08-01 00:00:00+00'
        + match_number * INTERVAL '30 minutes' AS start_time,
    1800 AS duration_s,
    90 AS average_badge,
    slot + 1 AS hero_id,
    slot // 4 AS assigned_lane,
    slot < 6 AS won,
    10000 + slot AS net_worth,
    0 AS player_rank_initial_calibration_games,
    match_number * 12 + slot AS account_id,
    [99, 599, 899, 1199] AS "stats.time_stamp_s",
    [1000 + slot, 6000 + slot, 9000 + slot, 10000 + slot] AS "stats.net_worth",
    [10, 20, 10] AS "items.item_id",
    [100, 600, 900] AS "items.game_time_s",
    [800, 0, 0] AS "items.sold_time_s",
    [0, 40, 0] AS "items.imbued_ability_id"
FROM range(1, 31) matches(match_number) CROSS JOIN range(12) players(slot);
