-- Each insert copies the cohort rows of one remote file. DuckLake reads only that file.
-- The start time has no upper limit, so that later runs can use the same rows.
INSERT INTO remote_cache.players
SELECT
    filename AS data_file,
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
    filename = $data_file
    AND start_time >= $since::TIMESTAMPTZ
    AND match_mode = $match_mode
    AND game_mode = $game_mode
    AND average_badge BETWEEN $minimum_badge AND $maximum_badge;
