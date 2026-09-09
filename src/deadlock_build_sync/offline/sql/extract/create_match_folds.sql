CREATE OR REPLACE TABLE match_folds AS
SELECT match_id,
       CASE WHEN epoch(min(start_time)) <= train_end THEN 'train'
            WHEN epoch(min(start_time)) <= validation_end THEN 'validation'
            ELSE 'test' END AS fold
FROM player_matches, split_boundaries
GROUP BY match_id, train_end, validation_end;
