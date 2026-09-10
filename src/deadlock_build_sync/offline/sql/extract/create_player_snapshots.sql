CREATE TABLE player_snapshots AS
SELECT match_id, player_slot,
       unnest("stats.time_stamp_s") AS stat_time,
       unnest("stats.net_worth") AS net_worth
FROM remote.main.match_player
INNER JOIN eligible_matches USING(match_id);
