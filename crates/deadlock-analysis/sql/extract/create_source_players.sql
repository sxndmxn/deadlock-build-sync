-- The copies filter the rows before this version selection
-- and before the 12-player check.
-- This gives the same rows when all versions of a player row have the same mode,
-- game mode, and badge, and when all players of a match have the same values.
-- On 2026-10-28, 7.5 million of 15.0 million keys had more than one version.
-- No key and no match had different values.
CREATE OR REPLACE TABLE source_players AS
WITH cohort_rows AS (
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
    FROM remote_cache.players
    UNION ALL
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
    FROM catalog_players
)

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
    "stats.net_worth"
FROM cohort_rows
WHERE start_time <= $as_of::TIMESTAMPTZ
QUALIFY row_number() OVER (
    PARTITION BY match_id, account_id, start_time
    ORDER BY created_at DESC
) = 1;
