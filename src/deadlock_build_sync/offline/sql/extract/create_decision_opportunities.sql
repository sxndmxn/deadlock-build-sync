CREATE TABLE decision_opportunities AS
WITH realized AS (
    SELECT *
    FROM first_purchases
    WHERE same_second_purchase_count = 1
    QUALIFY row_number() OVER (
        PARTITION BY match_id, player_slot, phase, tier
        ORDER BY buy_time, item_id
    ) = 1
), slates AS (
    SELECT tier, list_sort(list(item_id)) AS item_ids
    FROM item_assets
    GROUP BY tier
)
SELECT r.*,
       to_json(struct_pack(
           item_ids := s.item_ids,
           includes_save := true
       )) AS candidate_slate_json,
       cast(r.item_id AS VARCHAR) AS realized_action,
       false AS save_action_observed
FROM realized r
JOIN slates s USING (tier)
ORDER BY r.hero_id, r.match_id, r.player_slot, r.buy_time, r.item_id;
