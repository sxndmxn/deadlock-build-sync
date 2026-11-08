-- Remote files do not change, so the cache keeps the cohort rows of each file.
-- A row in remote_cache.files marks a complete copy of that file.
CREATE TABLE IF NOT EXISTS remote_cache.files (data_file VARCHAR PRIMARY KEY);

CREATE TABLE IF NOT EXISTS remote_cache.players AS
SELECT
    ''::VARCHAR AS data_file,
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
WHERE FALSE;
