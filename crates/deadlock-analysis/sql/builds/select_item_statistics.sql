WITH hero_totals AS (
    SELECT
        hero_id,
        count(*) AS hero_matches
    FROM player_matches
    WHERE
        average_badge BETWEEN $minimum_badge AND $maximum_badge
        AND NOT calibration
    GROUP BY hero_id
),

item_buyers AS (
    SELECT
        hero_id,
        item_id,
        count(*) AS buyer_matches,
        count(*) FILTER (WHERE won) AS buyer_wins
    FROM purchases
    WHERE
        average_badge BETWEEN $minimum_badge AND $maximum_badge
        AND NOT calibration
        AND item_purchase_ordinal = 1
    GROUP BY hero_id, item_id
)

SELECT
    b.hero_id,
    b.item_id,
    h.hero_matches,
    b.buyer_matches,
    b.buyer_wins
FROM item_buyers AS b
INNER JOIN hero_totals AS h ON b.hero_id = h.hero_id
ORDER BY b.hero_id, b.item_id;
