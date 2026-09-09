WITH firsts AS (
    SELECT p.* FROM first_purchases p
    JOIN _build_path_members m USING (match_id, player_slot)
    WHERE p.buy_time <= p.duration_s
), events AS (
    SELECT p.item_id, count(*) AS purchase_events
    FROM purchases p
    JOIN _build_path_members m USING (match_id, player_slot)
    WHERE p.buy_time <= p.duration_s
    GROUP BY p.item_id
), imbue_counts AS (
    SELECT p.item_id, p.imbued_ability_id,
           count(*) AS target_matches
    FROM firsts p
    WHERE p.imbued_ability_id > 0
      AND p.fold IN ('train', 'validation')
    GROUP BY p.item_id, p.imbued_ability_id
), ranked_imbues AS (
    SELECT *,
           sum(target_matches) OVER (PARTITION BY item_id)
               AS imbue_observations,
           row_number() OVER (
               PARTITION BY item_id
               ORDER BY target_matches DESC, imbued_ability_id
           ) AS target_rank
    FROM imbue_counts
), dominant_imbues AS (
    SELECT item_id, imbued_ability_id, target_matches,
           imbue_observations,
           target_matches / imbue_observations::DOUBLE AS target_share
    FROM ranked_imbues
    WHERE target_rank = 1
), items AS (
    SELECT
        p.hero_id, p.item_id, any_value(p.item_name) AS item_name,
        any_value(p.tier) AS tier, any_value(p.cost) AS cost,
        any_value(p.slot) AS slot, any_value(p.active) AS active,
        count(*) AS adopter_matches,
        count(*) FILTER (
            WHERE p.fold IN ('train', 'validation')
        ) AS selection_adopter_matches,
        count(*) FILTER (
            WHERE p.fold = 'train'
        ) AS training_adopter_matches,
        count(*) FILTER (
            WHERE p.fold = 'validation'
        ) AS validation_adopter_matches,
        count(*) FILTER (
            WHERE p.fold = 'test'
        ) AS test_adopter_matches,
        sum(p.won::INTEGER) AS wins,
        avg(p.won::INTEGER) AS raw_outcome_rate,
        median(p.buy_time) AS median_buy_time_s,
        quantile_cont(p.buy_time, 0.25) AS buy_time_q25_s,
        quantile_cont(p.buy_time, 0.75) AS buy_time_q75_s,
        median(p.own_net_worth_at_buy) AS median_valid_buy_net_worth,
        quantile_cont(p.own_net_worth_at_buy, 0.25) AS buy_nw_q25,
        quantile_cont(p.own_net_worth_at_buy, 0.75) AS buy_nw_q75,
        count(p.own_net_worth_at_buy) / count(*) AS valid_buy_nw_share,
        median(p.buy_time) FILTER (
            WHERE p.fold IN ('train', 'validation')
        ) AS selection_median_buy_time_s,
        median(p.own_net_worth_at_buy) FILTER (
            WHERE p.fold IN ('train', 'validation')
        ) AS selection_median_valid_buy_net_worth,
        quantile_cont(p.own_net_worth_at_buy, 0.25) FILTER (
            WHERE p.fold IN ('train', 'validation')
        ) AS selection_buy_nw_q25,
        quantile_cont(p.own_net_worth_at_buy, 0.75) FILTER (
            WHERE p.fold IN ('train', 'validation')
        ) AS selection_buy_nw_q75,
        count(p.own_net_worth_at_buy) FILTER (
            WHERE p.fold IN ('train', 'validation')
        ) AS selection_valid_buy_nw_observations,
        count(p.own_net_worth_at_buy) FILTER (
            WHERE p.fold = 'train'
        ) AS training_valid_buy_nw_observations,
        count(p.own_net_worth_at_buy) FILTER (
            WHERE p.fold = 'validation'
        ) AS validation_valid_buy_nw_observations,
        quantile_cont(p.own_net_worth_at_buy, 0.25) FILTER (
            WHERE p.fold = 'train'
        ) AS training_buy_nw_q25,
        quantile_cont(p.own_net_worth_at_buy, 0.75) FILTER (
            WHERE p.fold = 'train'
        ) AS training_buy_nw_q75,
        quantile_cont(p.own_net_worth_at_buy, 0.25) FILTER (
            WHERE p.fold = 'validation'
        ) AS validation_buy_nw_q25,
        quantile_cont(p.own_net_worth_at_buy, 0.75) FILTER (
            WHERE p.fold = 'validation'
        ) AS validation_buy_nw_q75
    FROM firsts p
    GROUP BY p.hero_id, p.item_id
    HAVING count(*) >= $minimum_support
)
SELECT i.*, e.purchase_events,
       d.imbued_ability_id, d.target_matches,
       d.imbue_observations, d.target_share,
       $member_count::BIGINT AS hero_player_matches,
       i.adopter_matches / $member_count::DOUBLE AS adoption_rate
FROM items i JOIN events e USING (item_id)
LEFT JOIN dominant_imbues d USING (item_id);
