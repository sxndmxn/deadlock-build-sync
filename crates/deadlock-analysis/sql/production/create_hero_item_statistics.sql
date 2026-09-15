CREATE TEMP TABLE _hero_item_statistics AS
WITH hero_matches AS (
    SELECT
        match_id,
        player_slot,
        won,
        duration_s
    FROM player_matches
    WHERE
        hero_id = $hero
        AND average_badge BETWEEN $minimum_badge AND $maximum_badge
),

population AS (
    SELECT count(*) AS eligible_player_matches
    FROM hero_matches
),

buyers AS (
    SELECT
        p.item_id,
        count(*) AS adopter_matches,
        sum(m.won::INTEGER) AS wins
    FROM first_purchases AS p
    INNER JOIN hero_matches AS m
        ON p.match_id = m.match_id AND p.player_slot = m.player_slot
    WHERE p.hero_id = $hero AND p.buy_time <= m.duration_s
    GROUP BY p.item_id
)

SELECT
    b.item_id,
    p.eligible_player_matches,
    b.adopter_matches,
    b.wins,
    b.adopter_matches / p.eligible_player_matches::DOUBLE AS adoption,
    b.wins / b.adopter_matches::DOUBLE AS observed_outcome_rate
FROM buyers AS b CROSS JOIN population AS p;
