SELECT count(*) AS excluded_matches FROM match_folds AS f
WHERE
    f.fold = $partition
    AND f.match_id NOT IN (SELECT e.match_id FROM experiment_matches AS e);
