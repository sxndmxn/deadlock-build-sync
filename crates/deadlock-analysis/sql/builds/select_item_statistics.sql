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
        u.hero_id,
        u.item_id,
        count(*) AS buyer_matches,
        count(*) FILTER (WHERE p.won) AS buyer_wins
    FROM purchases AS u
    INNER JOIN player_matches AS p
        ON
            u.match_id = p.match_id
            AND u.player_slot = p.player_slot
    WHERE
        u.average_badge BETWEEN $minimum_badge AND $maximum_badge
        AND NOT u.calibration
        AND u.item_purchase_ordinal = 1
    GROUP BY u.hero_id, u.item_id
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
