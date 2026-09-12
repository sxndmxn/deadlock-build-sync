CREATE OR REPLACE TEMP TABLE discovery_partitions AS
WITH matches AS (
    SELECT
        p.match_id,
        min(p.start_time) AS started
    FROM player_matches AS p INNER JOIN match_folds AS f ON p.match_id = f.match_id
    WHERE f.fold = 'train'
    GROUP BY p.match_id
)

SELECT
    match_id,
    CASE
        WHEN
            row_number() OVER (ORDER BY started, match_id)
            <= floor(count(*) OVER () * 0.75)
            THEN 'discovery'
        ELSE 'selection'
    END AS "partition"
FROM matches
UNION ALL
SELECT
    match_id,
    'validation' AS "partition"
FROM match_folds
WHERE fold = 'validation';
