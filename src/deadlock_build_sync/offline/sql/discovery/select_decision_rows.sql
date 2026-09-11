WITH eligible_decisions AS NOT MATERIALIZED (
    SELECT
        p.*,
        d."partition"
    FROM decision_opportunities AS p
    INNER JOIN discovery_partitions AS d ON p.match_id = d.match_id
    WHERE
        p.hero_id = $hero
        AND p.average_badge BETWEEN $minimum AND $maximum
        AND d."partition" IN ('discovery', 'validation')
        AND p.buy_time - p.state_observed_at_s BETWEEN 1 AND 300
),

checkpoints AS (
    SELECT DISTINCT
        match_id,
        team_id,
        buy_time
    FROM eligible_decisions
),

team_states AS (
    SELECT s.* FROM team_snapshots AS s
    SEMI JOIN checkpoints AS p ON s.match_id = p.match_id
),

states AS (
    SELECT
        p.*,
        own_state.team_net_worth AS own_team_net_worth,
        enemy_state.team_net_worth AS enemy_team_net_worth,
        own_state.observed_players AS own_team_observed_players,
        enemy_state.observed_players AS enemy_team_observed_players,
        own_state.stat_time AS own_observed,
        enemy_state.stat_time AS enemy_observed,
        own_state.team_net_worth - enemy_state.team_net_worth AS team_net_worth_lead
    FROM checkpoints AS p
    ASOF LEFT JOIN team_states AS own_state
        ON
            p.match_id = own_state.match_id AND p.team_id = own_state.team_id
            AND p.buy_time > own_state.stat_time
    ASOF LEFT JOIN team_states AS enemy_state
        ON
            p.match_id = enemy_state.match_id AND (1 - p.team_id) = enemy_state.team_id
            AND p.buy_time > enemy_state.stat_time
)

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
    p.fold,
    p.phase,
    p.state_age_s,
    p.prior_catalog_spend,
    p.prior_purchase_count,
    p.candidate_slate_json,
    p.realized_action,
    p.save_action_observed,
    p."partition",
    c.hero_ids AS enemy_heroes,
    s.own_team_net_worth,
    s.enemy_team_net_worth,
    s.own_team_observed_players,
    s.enemy_team_observed_players,
    s.team_net_worth_lead,
    s.own_observed,
    s.enemy_observed
FROM eligible_decisions AS p
INNER JOIN states AS s
    ON
        p.match_id = s.match_id AND p.team_id = s.team_id
        AND p.buy_time = s.buy_time
INNER JOIN compositions AS c
    ON p.match_id = c.match_id AND (1 - p.team_id) = c.team_id
ORDER BY p.match_id, p.player_slot, p.buy_time;
