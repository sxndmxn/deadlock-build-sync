CREATE OR REPLACE TEMP TABLE discovery_partitions AS
WITH matches AS (
    SELECT p.match_id, min(p.start_time) AS started
    FROM player_matches p JOIN match_folds f USING(match_id)
    WHERE f.fold='train' GROUP BY p.match_id
)
SELECT match_id,
    CASE WHEN row_number() OVER(ORDER BY started,match_id)
              <= floor(count(*) OVER()*0.75)
         THEN 'discovery' ELSE 'selection' END AS partition
FROM matches
UNION ALL
SELECT match_id, 'validation' FROM match_folds WHERE fold='validation';
