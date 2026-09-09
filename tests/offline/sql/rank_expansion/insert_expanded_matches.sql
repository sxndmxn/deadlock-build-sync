INSERT INTO player_matches
SELECT match_id+100, player_slot, 61, start_time FROM player_matches;
