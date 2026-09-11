CREATE OR REPLACE TEMP TABLE experiment_matches AS
SELECT f.match_id
FROM match_folds AS f
WHERE
    f.fold = $partition
    AND NOT EXISTS (
        SELECT 1
        FROM player_matches AS p
        WHERE p.match_id = f.match_id
        GROUP BY p.hero_id
        HAVING count(*) > 1
    );
