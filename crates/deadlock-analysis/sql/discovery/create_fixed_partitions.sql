CREATE OR REPLACE TEMP TABLE discovery_partitions AS
SELECT
    p.match_id,
    CASE
        WHEN epoch(min(p.start_time)) <= b.discovery_end THEN 'discovery'
        WHEN f.fold = 'train' THEN 'selection' ELSE f.fold
    END AS "partition"
FROM player_matches AS p
INNER JOIN match_folds AS f ON p.match_id = f.match_id
CROSS JOIN split_boundaries AS b
WHERE f.fold <> 'test'
GROUP BY p.match_id, f.fold, b.discovery_end;
