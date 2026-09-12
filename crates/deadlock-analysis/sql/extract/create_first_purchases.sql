CREATE TABLE first_purchases AS
WITH firsts AS (
    SELECT
        p.match_id,
        p.player_slot,
        p.team_id,
        p.hero_id,
        p.assigned_lane,
        p.average_badge,
        p.won,
        p.start_time,
        p.duration_s,
        p.final_net_worth,
        p.calibration,
        p.item_id,
        p.buy_time,
        p.sold_time,
        p.imbued_ability_id,
        p.item_name,
        p.class_name,
        p.tier,
        p."cost",
        p.slot,
        p.active,
        p.unique_item,
        p.component_items_json,
        p.own_net_worth_at_buy,
        p.state_observed_at_s,
        p.event_order,
        p.same_second_purchase_count,
        p.item_purchase_ordinal,
        f.fold,
        CASE
            WHEN p.buy_time < 540 THEN 0
            WHEN p.buy_time < 1200 THEN 1
            WHEN p.buy_time < 1800 THEN 2
            ELSE 3
        END AS phase
    FROM purchases AS p
    INNER JOIN match_folds AS f ON p.match_id = f.match_id
    WHERE p.item_purchase_ordinal = 1
),

own_state AS (
    SELECT
        f.*,
        s.team_net_worth AS own_team_net_worth,
        s.observed_players AS own_team_observed_players
    FROM firsts AS f
    ASOF LEFT JOIN team_snapshots AS s
        ON
            f.match_id = s.match_id
            AND f.team_id = s.team_id
            AND f.buy_time >= s.stat_time
),

both_states AS (
    SELECT
        o.*,
        s.team_net_worth AS enemy_team_net_worth,
        s.observed_players AS enemy_team_observed_players
    FROM own_state AS o
    ASOF LEFT JOIN team_snapshots AS s
        ON
            o.match_id = s.match_id
            AND (1 - o.team_id) = s.team_id
            AND o.buy_time >= s.stat_time
)

SELECT
    *,
    own_team_net_worth - enemy_team_net_worth AS team_net_worth_lead,
    buy_time - state_observed_at_s AS state_age_s,
    sum("cost") OVER (
        PARTITION BY match_id, player_slot
        ORDER BY buy_time
        RANGE BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
    ) AS prior_catalog_spend,
    count(*) OVER (
        PARTITION BY match_id, player_slot
        ORDER BY buy_time
        RANGE BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
    ) AS prior_purchase_count
FROM both_states
ORDER BY hero_id, match_id, player_slot, buy_time, item_id;
