WITH actors AS (
    SELECT
        p.match_id,
        p.player_slot,
        p.team_id,
        p.won,
        p.average_badge,
        p.start_time,
        d."partition"
    FROM player_matches AS p
    INNER JOIN discovery_partitions AS d ON p.match_id = d.match_id
    WHERE p.hero_id = $hero AND p.duration_s >= $ownership_before_seconds
),

player_states AS (
    SELECT
        s.match_id,
        s.player_slot,
        arg_max_null(s.net_worth, s.stat_time) AS wealth
    FROM player_snapshots AS s
    SEMI JOIN actors AS a
        ON s.match_id = a.match_id AND s.player_slot = a.player_slot
    WHERE
        s.stat_time >= $ownership_before_seconds - 300
        AND s.stat_time < $ownership_before_seconds
    GROUP BY s.match_id, s.player_slot
),

team_states AS (
    SELECT
        s.match_id,
        s.team_id,
        arg_max(
            struct_pack(wealth := s.team_net_worth, players := s.observed_players),
            s.stat_time
        ) AS latest_state
    FROM team_snapshots AS s
    SEMI JOIN actors AS a ON s.match_id = a.match_id
    WHERE
        s.stat_time >= $ownership_before_seconds - 300
        AND s.stat_time < $ownership_before_seconds
    GROUP BY s.match_id, s.team_id
),

states AS (
    SELECT
        a.*,
        p.wealth,
        c.hero_ids,
        own.latest_state['wealth'] - enemy.latest_state['wealth'] AS team_difference,
        CASE
            WHEN
                own.latest_state['players'] = 6 AND enemy.latest_state['players'] = 6
                AND own.latest_state['wealth'] + enemy.latest_state['wealth'] > 0
                THEN own.latest_state['wealth'] + enemy.latest_state['wealth']
        END AS team_wealth
    FROM actors AS a
    LEFT JOIN player_states AS p
        ON a.match_id = p.match_id AND a.player_slot = p.player_slot
    LEFT JOIN team_states AS own
        ON a.match_id = own.match_id AND a.team_id = own.team_id
    LEFT JOIN team_states AS enemy
        ON a.match_id = enemy.match_id AND (1 - a.team_id) = enemy.team_id
    LEFT JOIN compositions AS c
        ON a.match_id = c.match_id AND (1 - a.team_id) = c.team_id
),

landmarks AS (
    SELECT
        *,
        CASE WHEN wealth > 0 THEN wealth END AS observed_wealth,
        team_difference / team_wealth AS team_lead,
        CASE WHEN wealth > 0 THEN wealth * 12 / team_wealth END AS relative_wealth
    FROM states
)

SELECT
    match_id,
    player_slot,
    "partition",
    won,
    observed_wealth,
    team_lead,
    average_badge,
    relative_wealth,
    hero_ids
FROM landmarks
ORDER BY start_time, match_id, player_slot;
