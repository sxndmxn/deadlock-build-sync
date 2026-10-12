WITH target_counts AS (
    SELECT
        hero_id,
        item_id,
        imbued_ability_id AS ability_id,
        count(*) AS target_matches
    FROM purchases
    WHERE
        average_badge BETWEEN $minimum_badge AND $maximum_badge
        AND NOT calibration
        AND item_purchase_ordinal = 1
        AND imbued_ability_id > 0
    GROUP BY hero_id, item_id, imbued_ability_id
),

ranked_targets AS (
    SELECT
        hero_id,
        item_id,
        ability_id,
        target_matches,
        sum(target_matches) OVER (PARTITION BY hero_id, item_id) AS observations,
        row_number() OVER (
            PARTITION BY hero_id, item_id
            ORDER BY target_matches DESC, ability_id ASC
        ) AS target_rank
    FROM target_counts
)

SELECT
    hero_id,
    item_id,
    ability_id,
    target_matches,
    observations
FROM ranked_targets
WHERE target_rank = 1
ORDER BY hero_id, item_id;
