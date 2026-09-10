WITH purchases AS (
    SELECT p.* FROM first_purchases AS p
    INNER JOIN discovery_partitions AS d ON p.match_id = d.match_id
    WHERE
        d."partition" = 'discovery' AND p.hero_id = $hero
        AND p.average_badge BETWEEN $minimum_badge AND $maximum_badge
        AND p.same_second_purchase_count = 1 AND p.item_purchase_ordinal = 1
        AND p."cost" > 0 AND p.own_net_worth_at_buy > 0
        AND p.buy_time - p.state_observed_at_s BETWEEN 1 AND 120
),

own_state AS (
    SELECT
        p.*,
        s.team_net_worth AS own_wealth,
        s.observed_players AS own_count,
        s.stat_time AS own_observed
    FROM purchases AS p ASOF LEFT JOIN team_snapshots AS s
        ON
            p.match_id = s.match_id
            AND p.team_id = s.team_id
            AND p.buy_time > s.stat_time
),

both_states AS (
    SELECT
        p.*,
        s.team_net_worth AS enemy_wealth,
        s.observed_players AS enemy_count,
        s.stat_time AS enemy_observed
    FROM own_state AS p ASOF LEFT JOIN team_snapshots AS s
        ON
            p.match_id = s.match_id
            AND (1 - p.team_id) = s.team_id
            AND p.buy_time > s.stat_time
),

observations AS (
    SELECT
        item_id,
        won,
        least(11, floor(own_net_worth_at_buy / 4000.0))::INTEGER AS wealth_bin,
        CASE
            WHEN own_net_worth_at_buy * 12.0 / (own_wealth + enemy_wealth) < 0.90 THEN 0
            WHEN own_net_worth_at_buy * 12.0 / (own_wealth + enemy_wealth) > 1.10 THEN 2
            ELSE 1
        END AS relative_state
    FROM both_states
    WHERE
        own_count = 6 AND enemy_count = 6 AND own_wealth + enemy_wealth > 0
        AND buy_time - own_observed BETWEEN 1 AND 120
        AND buy_time - enemy_observed BETWEEN 1 AND 120
)

SELECT
    wealth_bin,
    relative_state,
    item_id,
    count(*) AS purchases,
    sum(won::INTEGER) AS wins
FROM observations
GROUP BY wealth_bin, relative_state, item_id
ORDER BY wealth_bin, relative_state, item_id;
