SELECT
    count(*) AS player_matches,
    median(p.final_net_worth) FILTER (
        WHERE f.fold IN ('train', 'validation')
    ) AS selection_median_final_net_worth
FROM player_matches AS p
INNER JOIN _build_path_members AS m
    ON p.match_id = m.match_id AND p.player_slot = m.player_slot
INNER JOIN match_folds AS f ON p.match_id = f.match_id;
