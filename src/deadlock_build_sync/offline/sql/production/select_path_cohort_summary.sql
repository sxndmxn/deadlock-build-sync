SELECT count(*),
       median(final_net_worth) FILTER (
           WHERE f.fold IN ('train', 'validation')
       )
FROM player_matches p
JOIN _build_path_members m USING (match_id, player_slot)
JOIN match_folds f USING (match_id);
