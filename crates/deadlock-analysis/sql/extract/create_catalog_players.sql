-- DuckLake can keep new rows in its catalog instead of a file. These rows can change,
-- so the cache does not keep them. In lake format 1.1, their file names start with
-- ducklake_inlined_data_. Check this prefix after each update of the duckdb crate.
CREATE OR REPLACE TEMP TABLE catalog_players AS
SELECT
    match_id,
    account_id,
    player_slot,
    team,
    hero_id,
    average_badge,
    won,
    start_time,
    duration_s,
    rewards_eligible,
    player_match_outcome,
    player_rank_initial_calibration_games,
    "items.item_id",
    "items.game_time_s",
    "items.sold_time_s",
    "items.imbued_ability_id",
    "stats.time_stamp_s",
    "stats.net_worth",
    created_at
FROM remote."main".match_player
WHERE
    starts_with(filename, 'ducklake_inlined_data_')
    AND start_time >= $since::TIMESTAMPTZ
    AND match_mode = $match_mode
    AND game_mode = $game_mode
    AND average_badge BETWEEN $minimum_badge AND $maximum_badge;
