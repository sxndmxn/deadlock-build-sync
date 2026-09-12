CREATE TABLE purchases AS
WITH expanded AS (
    SELECT
        p.match_id,
        p.player_slot,
        CASE WHEN p.team = 'Team0' THEN 0 ELSE 1 END AS team_id,
        p.hero_id,
        p.assigned_lane,
        p.average_badge,
        p.won,
        p.start_time,
        p.duration_s,
        p.net_worth AS final_net_worth,
        coalesce(p.player_rank_initial_calibration_games, 0) > 0 AS calibration,
        unnest(p."items.item_id") AS item_id,
        unnest(p."items.game_time_s") AS buy_time,
        unnest(p."items.sold_time_s") AS sold_time,
        unnest(p."items.imbued_ability_id") AS imbued_ability_id,
        p."stats.time_stamp_s" AS stat_times,
        p."stats.net_worth" AS stat_net_worths
    FROM remote."main".match_player AS p
    INNER JOIN eligible_matches AS e ON p.match_id = e.match_id
),

valid_purchases AS (
    SELECT
        e.*,
        a.item_name,
        a.class_name,
        a.tier,
        a."cost",
        a.slot,
        a.active,
        a.unique_item,
        a.component_items_json,
        list_last(list_transform(
            list_filter(
                list_zip(e.stat_times, e.stat_net_worths),
                x -> x[1] <= e.buy_time
            ),
            x -> x[2]
        )) AS own_net_worth_at_buy,
        list_last(list_transform(
            list_filter(
                list_zip(e.stat_times, e.stat_net_worths),
                x -> x[1] <= e.buy_time
            ),
            x -> x[1]
        )) AS state_observed_at_s
    FROM expanded AS e
    INNER JOIN item_assets AS a ON e.item_id = a.item_id
    WHERE e.buy_time > 0 AND e.buy_time <= e.duration_s
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
FROM valid_purchases
ORDER BY hero_id, match_id, player_slot, buy_time, event_order;
