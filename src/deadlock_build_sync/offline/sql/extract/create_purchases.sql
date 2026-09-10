CREATE TABLE purchases AS
WITH expanded AS (
    SELECT
        match_id,
        player_slot,
        CASE WHEN team = 'Team0' THEN 0 ELSE 1 END AS team_id,
        hero_id,
        assigned_lane,
        average_badge,
        won,
        start_time,
        duration_s,
        net_worth AS final_net_worth,
        coalesce(player_rank_initial_calibration_games, 0) > 0 AS calibration,
        unnest("items.item_id") AS item_id,
        unnest("items.game_time_s") AS buy_time,
        unnest("items.sold_time_s") AS sold_time,
        unnest("items.imbued_ability_id") AS imbued_ability_id,
        "stats.time_stamp_s" AS stat_times,
        "stats.net_worth" AS stat_net_worths
    FROM remote.main.match_player
    INNER JOIN eligible_matches USING (match_id)
), valid AS (
    SELECT e.*,
           a.item_name, a.class_name, a.tier, a.cost, a.slot,
           a.active, a.unique_item, a.component_items_json,
           list_last(list_transform(
               list_filter(
                   list_zip(stat_times, stat_net_worths),
                   x -> x[1] <= buy_time
               ),
               x -> x[2]
           )) AS own_net_worth_at_buy,
           list_last(list_transform(
               list_filter(
                   list_zip(stat_times, stat_net_worths),
                   x -> x[1] <= buy_time
               ),
               x -> x[1]
           )) AS state_observed_at_s
    FROM expanded e
    INNER JOIN item_assets a USING (item_id)
    WHERE buy_time > 0
)
SELECT
    * EXCLUDE (stat_times, stat_net_worths),
    row_number() OVER (
        PARTITION BY match_id, player_slot
        ORDER BY buy_time, item_id
    ) AS event_order,
    count(*) OVER (
        PARTITION BY match_id, player_slot, buy_time
    ) AS same_second_purchase_count,
    row_number() OVER (
        PARTITION BY match_id, player_slot, item_id
        ORDER BY buy_time, sold_time
    ) AS item_purchase_ordinal
FROM valid
ORDER BY hero_id, match_id, player_slot, buy_time, event_order;
