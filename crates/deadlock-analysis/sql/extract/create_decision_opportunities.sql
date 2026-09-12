CREATE TABLE decision_opportunities AS
WITH realized AS (
    SELECT
        match_id,
        player_slot,
        team_id,
        hero_id,
        assigned_lane,
        average_badge,
        won,
        start_time,
        duration_s,
        final_net_worth,
        calibration,
        item_id,
        buy_time,
        sold_time,
        imbued_ability_id,
        item_name,
        class_name,
        tier,
        "cost",
        slot,
        active,
        unique_item,
        component_items_json,
        own_net_worth_at_buy,
        state_observed_at_s,
        event_order,
        same_second_purchase_count,
        item_purchase_ordinal,
        fold,
        phase,
        own_team_net_worth,
        own_team_observed_players,
        enemy_team_net_worth,
        enemy_team_observed_players,
        team_net_worth_lead,
        state_age_s,
        prior_catalog_spend,
        prior_purchase_count
    FROM first_purchases
    WHERE same_second_purchase_count = 1
    QUALIFY row_number() OVER (
        PARTITION BY match_id, player_slot, phase, tier
        ORDER BY buy_time, item_id
    ) = 1
),

slates AS (
    SELECT
        tier,
        list_sort(list(item_id)) AS item_ids
    FROM item_assets
    GROUP BY tier
)

SELECT
    r.match_id,
    r.player_slot,
    r.team_id,
    r.hero_id,
    r.assigned_lane,
    r.average_badge,
    r.won,
    r.start_time,
    r.duration_s,
    r.final_net_worth,
    r.calibration,
    r.item_id,
    r.buy_time,
    r.sold_time,
    r.imbued_ability_id,
    r.item_name,
    r.class_name,
    r.tier,
    r."cost",
    r.slot,
    r.active,
    r.unique_item,
    r.component_items_json,
    r.own_net_worth_at_buy,
    r.state_observed_at_s,
    r.event_order,
    r.same_second_purchase_count,
    r.item_purchase_ordinal,
    r.fold,
    r.phase,
    r.own_team_net_worth,
    r.own_team_observed_players,
    r.enemy_team_net_worth,
    r.enemy_team_observed_players,
    r.team_net_worth_lead,
    r.state_age_s,
    r.prior_catalog_spend,
    r.prior_purchase_count,
    to_json(struct_pack(
        item_ids := s.item_ids,
        includes_save := TRUE
    )) AS candidate_slate_json,
    (r.item_id)::VARCHAR AS realized_action,
    FALSE AS save_action_observed
FROM realized AS r
INNER JOIN slates AS s ON r.tier = s.tier
ORDER BY r.hero_id, r.match_id, r.player_slot, r.buy_time, r.item_id;
