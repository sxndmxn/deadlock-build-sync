WITH landmarks AS (
    SELECT unnest([360, 540, 720, 900, 1200, 1500, 1800, 2100]) AS landmark_s
),

players AS (
    SELECT
        p.match_id,
        p.player_slot,
        p.team_id,
        p.hero_id,
        p.won,
        p.average_badge,
        p.duration_s,
        f.fold
    FROM player_matches AS p
    INNER JOIN match_folds AS f ON p.match_id = f.match_id
    WHERE
        p.average_badge BETWEEN $minimum_badge AND $maximum_badge
        AND NOT p.calibration
),

states AS (
    SELECT
        pl.match_id,
        pl.player_slot,
        pl.hero_id,
        pl.won,
        pl.average_badge,
        pl.fold,
        l.landmark_s,
        s.net_worth,
        (own_team.team_net_worth - enemy_team.team_net_worth)
        / (own_team.team_net_worth + enemy_team.team_net_worth) AS team_lead
    FROM players AS pl
    INNER JOIN landmarks AS l ON pl.duration_s > l.landmark_s
    INNER JOIN player_snapshots AS s
        ON
            pl.match_id = s.match_id
            AND pl.player_slot = s.player_slot
            AND l.landmark_s = s.stat_time
    INNER JOIN team_snapshots AS own_team
        ON
            pl.match_id = own_team.match_id
            AND pl.team_id = own_team.team_id
            AND l.landmark_s = own_team.stat_time
    INNER JOIN team_snapshots AS enemy_team
        ON
            pl.match_id = enemy_team.match_id
            AND pl.team_id <> enemy_team.team_id
            AND l.landmark_s = enemy_team.stat_time
    WHERE
        s.net_worth IS NOT NULL
        AND own_team.team_net_worth + enemy_team.team_net_worth > 0
),

owned_items AS (
    SELECT
        st.match_id,
        st.player_slot,
        st.landmark_s,
        list_sort(list(DISTINCT pu.item_id)) AS item_ids
    FROM states AS st
    INNER JOIN purchases AS pu
        ON
            st.match_id = pu.match_id
            AND st.player_slot = pu.player_slot
    WHERE
        pu.buy_time <= st.landmark_s
        AND (pu.sold_time = 0 OR pu.sold_time > st.landmark_s)
    GROUP BY st.match_id, st.player_slot, st.landmark_s
)

SELECT
    st.hero_id,
    st.fold,
    st.landmark_s,
    st.won,
    st.average_badge,
    st.net_worth,
    st.team_lead::DOUBLE AS team_lead,
    coalesce(o.item_ids, []) AS item_ids
FROM states AS st
LEFT JOIN owned_items AS o
    ON
        st.match_id = o.match_id
        AND st.player_slot = o.player_slot
        AND st.landmark_s = o.landmark_s
ORDER BY st.hero_id, st.landmark_s, st.match_id, st.player_slot;
