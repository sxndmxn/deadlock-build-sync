CREATE TABLE player_snapshots AS
SELECT
    p.match_id,
    p.player_slot,
    unnest(p."stats.time_stamp_s") AS stat_time,
    unnest(p."stats.net_worth") AS net_worth
FROM remote."main".match_player AS p
INNER JOIN eligible_matches AS e ON p.match_id = e.match_id;
