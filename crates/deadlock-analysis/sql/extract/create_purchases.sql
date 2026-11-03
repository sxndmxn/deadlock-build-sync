CREATE OR REPLACE TABLE purchases AS
WITH expanded AS (
    SELECT
        p.match_id,
        p.player_slot,
        p.hero_id,
        p.average_badge,
        p.duration_s,
        coalesce(p.player_rank_initial_calibration_games, 0) > 0 AS calibration,
        unnest(p."items.item_id") AS item_id,
        unnest(p."items.game_time_s") AS buy_time,
        unnest(p."items.sold_time_s") AS sold_time,
        unnest(p."items.imbued_ability_id") AS imbued_ability_id,
        p."stats.time_stamp_s" AS stat_times,
        p."stats.net_worth" AS stat_net_worths
    FROM source_players AS p
    INNER JOIN eligible_matches AS e ON p.match_id = e.match_id
),

valid_purchases AS (
    SELECT
        e.match_id,
        e.player_slot,
        e.hero_id,
        e.average_badge,
        e.calibration,
        e.item_id,
        e.buy_time,
        e.sold_time,
        e.imbued_ability_id,
        -- SQLFluff 4.3 reads DuckDB lambda parameters as column references.
        -- noqa: disable=RF02
        list_last(list_transform(
            list_filter(
                list_zip(e.stat_times, e.stat_net_worths),
                LAMBDA x: x[1] <= e.buy_time
            ),
            LAMBDA x: x[2]
        )) AS own_net_worth_at_buy
        -- noqa: enable=RF02
    FROM expanded AS e
    SEMI JOIN item_assets AS a ON e.item_id = a.item_id
    WHERE e.buy_time > 0 AND e.buy_time <= e.duration_s
)

SELECT
    match_id,
    player_slot,
    hero_id,
    average_badge,
    calibration,
    item_id,
    buy_time,
    sold_time,
    imbued_ability_id,
    own_net_worth_at_buy,
    row_number() OVER (
        PARTITION BY match_id, player_slot, item_id
        ORDER BY buy_time, sold_time
    ) AS item_purchase_ordinal
FROM valid_purchases;
