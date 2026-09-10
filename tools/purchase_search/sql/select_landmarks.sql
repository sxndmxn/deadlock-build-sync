WITH actors AS (
    SELECT
        p.*,
        checkpoints."checkpoint"
    FROM player_matches AS p INNER JOIN match_folds AS f ON p.match_id = f.match_id
    INNER JOIN experiment_matches AS e ON p.match_id = e.match_id
    CROSS JOIN (VALUES (600), (1201), (1801)) AS checkpoints ("checkpoint")
    WHERE
        f.fold = $partition AND p.hero_id = $hero
        AND p.duration_s >= checkpoints."checkpoint"
),

personal AS (
    SELECT
        a.*,
        s.net_worth AS wealth,
        s.stat_time AS observed
    FROM actors AS a ASOF LEFT JOIN player_snapshots AS s
        ON
            a.match_id = s.match_id AND a.player_slot = s.player_slot
            AND a."checkpoint" > s.stat_time
),

own_state AS (
    SELECT
        a.*,
        s.team_net_worth AS own_wealth,
        s.observed_players AS own_count,
        s.stat_time AS own_observed
    FROM personal AS a ASOF LEFT JOIN team_snapshots AS s
        ON
            a.match_id = s.match_id AND a.team_id = s.team_id
            AND a."checkpoint" > s.stat_time
),

both_states AS (
    SELECT
        a.*,
        s.team_net_worth AS enemy_wealth,
        s.observed_players AS enemy_count,
        s.stat_time AS enemy_observed
    FROM own_state AS a ASOF LEFT JOIN team_snapshots AS s
        ON
            a.match_id = s.match_id AND (1 - a.team_id) = s.team_id
            AND a."checkpoint" > s.stat_time
),

landmarks AS (
    SELECT
        match_id,
        player_slot,
        "checkpoint",
        won,
        wealth,
        CASE
            WHEN
                wealth > 0 AND own_count = 6 AND enemy_count = 6
                AND "checkpoint" - observed BETWEEN 1 AND $freshness
                AND "checkpoint" - own_observed BETWEEN 1 AND $freshness
                AND "checkpoint" - enemy_observed BETWEEN 1 AND $freshness
                AND own_wealth + enemy_wealth > 0
                THEN CASE
                    WHEN wealth * 12.0 / (own_wealth + enemy_wealth) < 0.90 THEN 0
                    WHEN wealth * 12.0 / (own_wealth + enemy_wealth) > 1.10 THEN 2
                    ELSE 1
                END
            ELSE -1
        END AS relative_state
    FROM both_states
)

SELECT
    match_id,
    player_slot,
    "checkpoint",
    won,
    relative_state,
    wealth
FROM landmarks
ORDER BY match_id, player_slot, "checkpoint";
