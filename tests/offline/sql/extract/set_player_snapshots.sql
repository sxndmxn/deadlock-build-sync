UPDATE remote."main".match_player
SET "stats.time_stamp_s" = ?, "stats.net_worth" = ?
WHERE match_id = 1 AND player_slot = 0;
