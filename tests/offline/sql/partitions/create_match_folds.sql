CREATE TABLE match_folds AS SELECT i AS match_id, CASE WHEN i<8 THEN 'train' WHEN i=8 THEN 'validation' ELSE 'test' END AS fold FROM range(10) t(i);
