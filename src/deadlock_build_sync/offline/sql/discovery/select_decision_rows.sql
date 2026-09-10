SELECT p.* EXCLUDE(own_team_net_worth, enemy_team_net_worth,
                  own_team_observed_players, enemy_team_observed_players,
                  team_net_worth_lead),
       d.partition, c.hero_ids AS enemy_heroes,
       own_state.team_net_worth AS own_team_net_worth,
       enemy_state.team_net_worth AS enemy_team_net_worth,
       own_state.observed_players AS own_team_observed_players,
       enemy_state.observed_players AS enemy_team_observed_players,
       own_state.team_net_worth-enemy_state.team_net_worth AS team_net_worth_lead,
       own_state.stat_time AS own_observed, enemy_state.stat_time AS enemy_observed
FROM decision_opportunities p JOIN discovery_partitions d USING(match_id)
JOIN compositions c ON p.match_id=c.match_id AND (1-p.team_id)=c.team_id
ASOF LEFT JOIN team_snapshots own_state
  ON p.match_id=own_state.match_id AND p.team_id=own_state.team_id
     AND p.buy_time>own_state.stat_time
ASOF LEFT JOIN team_snapshots enemy_state
  ON p.match_id=enemy_state.match_id AND (1-p.team_id)=enemy_state.team_id
     AND p.buy_time>enemy_state.stat_time
WHERE p.hero_id=$hero AND p.average_badge BETWEEN $minimum AND $maximum AND d.partition IN ('discovery','validation')
  AND p.buy_time-p.state_observed_at_s BETWEEN 1 AND 300
ORDER BY p.match_id,p.player_slot,p.buy_time;
