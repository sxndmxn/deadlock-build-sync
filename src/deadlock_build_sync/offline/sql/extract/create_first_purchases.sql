CREATE TABLE first_purchases AS
WITH firsts AS (
    SELECT p.*, f.fold,
           CASE
               WHEN buy_time < 540 THEN 0
               WHEN buy_time < 1200 THEN 1
               WHEN buy_time < 1800 THEN 2
               ELSE 3
           END AS phase
    FROM purchases p
    JOIN match_folds f USING (match_id)
    WHERE item_purchase_ordinal = 1
), own_state AS (
    SELECT f.*, s.team_net_worth AS own_team_net_worth,
           s.observed_players AS own_team_observed_players
    FROM firsts f
    ASOF LEFT JOIN team_snapshots s
        ON f.match_id = s.match_id
       AND f.team_id = s.team_id
       AND f.buy_time >= s.stat_time
), both_states AS (
    SELECT o.*, s.team_net_worth AS enemy_team_net_worth,
           s.observed_players AS enemy_team_observed_players
    FROM own_state o
    ASOF LEFT JOIN team_snapshots s
        ON o.match_id = s.match_id
       AND (1 - o.team_id) = s.team_id
       AND o.buy_time >= s.stat_time
)
SELECT *,
       own_team_net_worth - enemy_team_net_worth AS team_net_worth_lead,
       buy_time - state_observed_at_s AS state_age_s,
       sum(cost) OVER (
           PARTITION BY match_id, player_slot
           ORDER BY buy_time
           RANGE BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
       ) AS prior_catalog_spend,
       count(*) OVER (
           PARTITION BY match_id, player_slot
           ORDER BY buy_time
           RANGE BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
       ) AS prior_purchase_count
FROM both_states
ORDER BY hero_id, match_id, player_slot, buy_time, item_id;
