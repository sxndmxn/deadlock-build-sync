SELECT
    match_id,
    fold
FROM match_folds
WHERE match_id < 100
ORDER BY match_id;
