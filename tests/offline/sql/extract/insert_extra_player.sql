INSERT INTO remote."main".match_player
SELECT
    match_id,
    12 AS player_slot,
    team,
    player_match_outcome,
    rewards_eligible,
    match_mode,
    game_mode,
    start_time,
    duration_s,
    $minimum_badge AS average_badge,
    13 AS hero_id,
    assigned_lane,
    won,
    net_worth,
    player_rank_initial_calibration_games,
    account_id,
    "stats.time_stamp_s",
    "stats.net_worth",
    "items.item_id",
    "items.game_time_s",
    "items.sold_time_s",
    "items.imbued_ability_id"
FROM remote."main".match_player
WHERE match_id = 1 AND player_slot = 0;
