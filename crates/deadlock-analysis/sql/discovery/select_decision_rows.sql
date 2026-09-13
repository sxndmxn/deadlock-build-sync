WITH eligible_decisions AS NOT MATERIALIZED (
    SELECT
        p.match_id,
        p.player_slot,
        p.team_id,
        p.average_badge,
        p.won,
        p.item_id,
        p.buy_time,
        p.own_net_worth_at_buy,
        p.state_observed_at_s,
        p.phase,
        p.state_age_s,
        p.prior_catalog_spend,
        p.prior_purchase_count,
        d."partition"
    FROM decision_opportunities AS p
    INNER JOIN discovery_partitions AS d ON p.match_id = d.match_id
    WHERE
        p.hero_id = $hero
        AND p.average_badge BETWEEN $minimum AND $maximum
        AND d."partition" IN ('discovery', 'validation')
        AND p.buy_time - p.state_observed_at_s BETWEEN 1 AND 300
),

checkpoints AS (
    SELECT DISTINCT
        match_id,
        team_id,
        buy_time
    FROM eligible_decisions
),

team_states AS (
    SELECT
        s.match_id,
        s.team_id,
        s.team_net_worth,
        s.observed_players,
        s.stat_time
    FROM team_snapshots AS s
    SEMI JOIN checkpoints AS p ON s.match_id = p.match_id
),

states AS (
    SELECT
        p.match_id,
        p.team_id,
        p.buy_time,
        own_state.team_net_worth AS own_team_net_worth,
        enemy_state.team_net_worth AS enemy_team_net_worth,
        own_state.observed_players AS own_team_observed_players,
        enemy_state.observed_players AS enemy_team_observed_players,
        CASE
            WHEN
                own_state.stat_time >= 0
                AND p.buy_time - own_state.stat_time BETWEEN 1 AND 300
                THEN own_state.stat_time
        END AS own_observed,
        CASE
            WHEN
                enemy_state.stat_time >= 0
                AND p.buy_time - enemy_state.stat_time BETWEEN 1 AND 300
                THEN enemy_state.stat_time
        END AS enemy_observed,
        own_state.team_net_worth - enemy_state.team_net_worth AS team_net_worth_lead
    FROM checkpoints AS p
    ASOF LEFT JOIN team_states AS own_state
        ON
            p.match_id = own_state.match_id AND p.team_id = own_state.team_id
            AND p.buy_time > own_state.stat_time
    ASOF LEFT JOIN team_states AS enemy_state
        ON
            p.match_id = enemy_state.match_id AND (1 - p.team_id) = enemy_state.team_id
            AND p.buy_time > enemy_state.stat_time
)

SELECT
    p.team_id,
    s.enemy_observed,
    struct_pack(
        match_id := p.match_id,
        player_slot := p.player_slot,
        average_badge := p.average_badge,
        won := p.won,
        item_id := p.item_id,
        buy_time := p.buy_time,
        own_net_worth_at_buy := p.own_net_worth_at_buy,
        state_observed_at_s := p.state_observed_at_s,
        fold
        := CASE WHEN p."partition" = 'discovery' THEN 'train' ELSE 'validation' END,
        phase := p.phase,
        state_age_s := p.state_age_s,
        prior_catalog_spend := p.prior_catalog_spend,
        prior_purchase_count := p.prior_purchase_count,
        enemy_heroes
        := CASE WHEN s.enemy_observed IS NOT NULL THEN c.hero_ids ELSE [] END,
        own_team_net_worth := s.own_team_net_worth,
        enemy_team_net_worth := s.enemy_team_net_worth,
        team_net_worth_lead := s.team_net_worth_lead,
        relative_wealth := CASE
            WHEN
                s.own_team_observed_players = 6 AND s.enemy_team_observed_players = 6
                AND s.own_observed IS NOT NULL AND s.enemy_observed IS NOT NULL
                AND coalesce(s.own_team_net_worth::DOUBLE, 0.0)
                + coalesce(s.enemy_team_net_worth::DOUBLE, 0.0) > 0.0
                THEN
                    p.own_net_worth_at_buy::DOUBLE * 12.0
                    / (
                        coalesce(s.own_team_net_worth::DOUBLE, 0.0)
                        + coalesce(s.enemy_team_net_worth::DOUBLE, 0.0)
                    )
        END
    ) AS decision
FROM eligible_decisions AS p
INNER JOIN states AS s
    ON
        p.match_id = s.match_id AND p.team_id = s.team_id
        AND p.buy_time = s.buy_time
INNER JOIN compositions AS c
    ON p.match_id = c.match_id AND (1 - p.team_id) = c.team_id
ORDER BY p.match_id, p.player_slot, p.buy_time;
