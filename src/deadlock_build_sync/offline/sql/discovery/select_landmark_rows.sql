WITH actors AS (
    SELECT p.*, d.partition, 1199 AS checkpoint
    FROM player_matches p JOIN discovery_partitions d USING(match_id)
    WHERE p.hero_id=$hero AND p.duration_s>=1200
), personal AS (
    SELECT a.*, s.net_worth AS wealth, s.stat_time AS observed
    FROM actors a ASOF LEFT JOIN player_snapshots s
    ON a.match_id=s.match_id AND a.player_slot=s.player_slot
       AND a.checkpoint>=s.stat_time
), own_team AS (
    SELECT p.*, t.team_net_worth AS own_wealth,
           t.observed_players AS own_count, t.stat_time AS own_observed
    FROM personal p ASOF LEFT JOIN team_snapshots t
    ON p.match_id=t.match_id AND p.team_id=t.team_id
       AND p.checkpoint>=t.stat_time
), both_teams AS (
    SELECT p.*, t.team_net_worth AS enemy_wealth,
           t.observed_players AS enemy_count, t.stat_time AS enemy_observed
    FROM own_team p ASOF LEFT JOIN team_snapshots t
    ON p.match_id=t.match_id AND (1-p.team_id)=t.team_id
       AND p.checkpoint>=t.stat_time
)
SELECT p.match_id, p.player_slot, p.partition, p.won,
       CASE WHEN p.wealth>0 AND 1200-p.observed BETWEEN 1 AND 300 THEN p.wealth END,
       CASE WHEN p.own_count=6 AND p.enemy_count=6
            AND 1200-p.own_observed BETWEEN 1 AND 300
            AND 1200-p.enemy_observed BETWEEN 1 AND 300
            AND p.own_wealth+p.enemy_wealth>0
            THEN (p.own_wealth-p.enemy_wealth)/(p.own_wealth+p.enemy_wealth) END,
       p.average_badge,
       CASE WHEN p.wealth>0 AND p.own_count=6 AND p.enemy_count=6
            AND 1200-p.observed BETWEEN 1 AND 300
            AND 1200-p.own_observed BETWEEN 1 AND 300
            AND 1200-p.enemy_observed BETWEEN 1 AND 300
            AND p.own_wealth+p.enemy_wealth>0
            THEN p.wealth*12/(p.own_wealth+p.enemy_wealth) END,
       c.hero_ids
FROM both_teams p LEFT JOIN compositions c
  ON p.match_id=c.match_id AND (1-p.team_id)=c.team_id
ORDER BY p.start_time, p.match_id, p.player_slot;
