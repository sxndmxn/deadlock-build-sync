WITH purchases AS (
    SELECT
        p.match_id,
        p.team_id,
        p.item_id,
        p.won,
        p.buy_time,
        p.own_net_worth_at_buy
    FROM first_purchases AS p
    INNER JOIN discovery_partitions AS d ON p.match_id = d.match_id
    WHERE
        d."partition" = 'discovery' AND p.hero_id = $hero
        AND p.average_badge BETWEEN $minimum_badge AND $maximum_badge
        AND p.same_second_purchase_count = 1 AND p.item_purchase_ordinal = 1
        AND p."cost" > 0 AND p.own_net_worth_at_buy > 0
        AND p.buy_time - p.state_observed_at_s BETWEEN 1 AND 120
),

team_states AS (
    SELECT s.* FROM team_snapshots AS s
    SEMI JOIN purchases AS p ON s.match_id = p.match_id
),

observations AS (
    SELECT
        p.item_id,
        p.won,
        least(11, floor(p.own_net_worth_at_buy / 4000.0))::INTEGER AS wealth_bin,
        CASE
            WHEN
                p.own_net_worth_at_buy * 12.0
                / (own.team_net_worth + enemy.team_net_worth) < 0.90 THEN 0
            WHEN
                p.own_net_worth_at_buy * 12.0
                / (own.team_net_worth + enemy.team_net_worth) > 1.10 THEN 2
            ELSE 1
        END AS relative_state
    FROM purchases AS p
    ASOF JOIN team_states AS own
        ON
            p.match_id = own.match_id AND p.team_id = own.team_id
            AND p.buy_time > own.stat_time
    ASOF JOIN team_states AS enemy
        ON
            p.match_id = enemy.match_id AND (1 - p.team_id) = enemy.team_id
            AND p.buy_time > enemy.stat_time
    WHERE
        own.observed_players = 6 AND enemy.observed_players = 6
        AND own.team_net_worth + enemy.team_net_worth > 0
        AND p.buy_time - own.stat_time BETWEEN 1 AND 120
        AND p.buy_time - enemy.stat_time BETWEEN 1 AND 120
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
