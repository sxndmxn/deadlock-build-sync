CREATE TABLE match_folds AS
SELECT
    folds.match_id,
    folds.fold
FROM (VALUES (1, 'train'), (2, 'train'), (3, 'validation'), (4, 'test'))
    AS folds (match_id, fold);
