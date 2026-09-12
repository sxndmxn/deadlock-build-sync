CREATE OR REPLACE TABLE match_folds AS
SELECT
    p.match_id,
    CASE
        WHEN epoch(min(p.start_time)) <= b.train_end THEN 'train'
        WHEN epoch(min(p.start_time)) <= b.validation_end THEN 'validation'
        ELSE 'test'
    END AS fold
FROM player_matches AS p
CROSS JOIN split_boundaries AS b
GROUP BY p.match_id, b.train_end, b.validation_end;
