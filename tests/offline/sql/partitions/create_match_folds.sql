CREATE TABLE match_folds AS
SELECT
    t.i AS match_id,
    CASE WHEN t.i < 8 THEN 'train' WHEN t.i = 8 THEN 'validation' ELSE 'test' END
        AS fold
FROM range(10) AS t (i);
