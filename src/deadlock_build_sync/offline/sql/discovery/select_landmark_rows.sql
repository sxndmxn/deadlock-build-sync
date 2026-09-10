WITH actors AS (
    SELECT
        p.*,
        d."partition",
        $ownership_before_seconds - 1 AS checkpoint_s
    FROM player_matches AS p
    INNER JOIN discovery_partitions AS d ON p.match_id = d.match_id
    WHERE p.hero_id = $hero AND p.duration_s >= $ownership_before_seconds
),

personal AS (
    SELECT
        a.*,
        s.net_worth AS wealth,
        s.stat_time AS observed
    FROM actors AS a ASOF LEFT JOIN player_snapshots AS s
        ON
            a.match_id = s.match_id AND a.player_slot = s.player_slot
            AND a.checkpoint_s >= s.stat_time
),

own_team AS (
    SELECT
        p.*,
        t.team_net_worth AS own_wealth,
        t.observed_players AS own_count,
        t.stat_time AS own_observed
    FROM personal AS p ASOF LEFT JOIN team_snapshots AS t
        ON
            p.match_id = t.match_id AND p.team_id = t.team_id
            AND p.checkpoint_s >= t.stat_time
),

both_teams AS (
    SELECT
        p.*,
        t.team_net_worth AS enemy_wealth,
        t.observed_players AS enemy_count,
        t.stat_time AS enemy_observed
    FROM own_team AS p ASOF LEFT JOIN team_snapshots AS t
        ON
            p.match_id = t.match_id AND (1 - p.team_id) = t.team_id
            AND p.checkpoint_s >= t.stat_time
),

landmarks AS (
    SELECT
        p.match_id,
        p.player_slot,
        p."partition",
        p.won,
        p.average_badge,
        c.hero_ids,
        p.start_time,
        CASE
            WHEN
                p.wealth > 0
                AND $ownership_before_seconds - p.observed BETWEEN 1 AND 300
                THEN p.wealth
        END AS observed_wealth,
        CASE
            WHEN
                p.own_count = 6 AND p.enemy_count = 6
                AND $ownership_before_seconds - p.own_observed BETWEEN 1 AND 300
                AND $ownership_before_seconds - p.enemy_observed BETWEEN 1 AND 300
                AND p.own_wealth + p.enemy_wealth > 0
                THEN (p.own_wealth - p.enemy_wealth) / (p.own_wealth + p.enemy_wealth)
        END AS team_lead,
        CASE
            WHEN
                p.wealth > 0 AND p.own_count = 6 AND p.enemy_count = 6
                AND $ownership_before_seconds - p.observed BETWEEN 1 AND 300
                AND $ownership_before_seconds - p.own_observed BETWEEN 1 AND 300
                AND $ownership_before_seconds - p.enemy_observed BETWEEN 1 AND 300
                AND p.own_wealth + p.enemy_wealth > 0
                THEN p.wealth * 12 / (p.own_wealth + p.enemy_wealth)
        END AS relative_wealth
    FROM both_teams AS p LEFT JOIN compositions AS c
        ON p.match_id = c.match_id AND (1 - p.team_id) = c.team_id
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
