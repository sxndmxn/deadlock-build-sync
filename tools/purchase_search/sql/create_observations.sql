CREATE OR REPLACE TEMP TABLE experiment_observations AS
WITH purchases_in_partition AS (
    SELECT
        p.match_id,
        p.player_slot,
        p.hero_id,
        p.team_id,
        p.won,
        p.item_id,
        p.buy_time,
        p.own_net_worth_at_buy,
        p.state_observed_at_s
    FROM first_purchases AS p
    WHERE
        p.fold = $partition
        AND p.match_id IN (SELECT e.match_id FROM experiment_matches AS e)
        AND p.average_badge BETWEEN 71 AND 115
        AND p.same_second_purchase_count = 1
        AND p.item_purchase_ordinal = 1
        AND p."cost" > 0
        AND p.own_net_worth_at_buy > 0
        AND p.buy_time - p.state_observed_at_s BETWEEN 1 AND $freshness
),

own_state AS (
    SELECT
        p.*,
        s.team_net_worth AS own_wealth,
        s.observed_players AS own_count,
        s.stat_time AS own_observed
    FROM purchases_in_partition AS p
    ASOF LEFT JOIN team_snapshots AS s
        ON
            p.match_id = s.match_id AND p.team_id = s.team_id
            AND p.buy_time > s.stat_time
),

both_states AS (
    SELECT
        p.*,
        s.team_net_worth AS enemy_wealth,
        s.observed_players AS enemy_count,
        s.stat_time AS enemy_observed
    FROM own_state AS p
    ASOF LEFT JOIN team_snapshots AS s
        ON
            p.match_id = s.match_id AND (1 - p.team_id) = s.team_id
            AND p.buy_time > s.stat_time
),

usable AS (
    SELECT
        *,
        own_net_worth_at_buy * 12.0 / (own_wealth + enemy_wealth) AS relative_wealth
    FROM both_states
    WHERE
        own_count = 6 AND enemy_count = 6
        AND buy_time - own_observed BETWEEN 1 AND $freshness
        AND buy_time - enemy_observed BETWEEN 1 AND $freshness
        AND own_wealth + enemy_wealth > 0
)

SELECT
    match_id,
    player_slot,
    hero_id,
    won,
    item_id,
    buy_time,
    own_net_worth_at_buy AS net_worth,
    least(11, floor(own_net_worth_at_buy / 4000.0))::INTEGER AS wealth_bin,
    CASE
        WHEN relative_wealth < 0.90 THEN 0
        WHEN relative_wealth > 1.10 THEN 2 ELSE 1
    END AS relative_state
FROM usable;
