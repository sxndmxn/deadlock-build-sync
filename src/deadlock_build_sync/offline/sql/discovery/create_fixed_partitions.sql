CREATE OR REPLACE TEMP TABLE discovery_partitions AS
SELECT p.match_id,
       CASE WHEN epoch(min(p.start_time)) <= b.discovery_end THEN 'discovery'
            WHEN f.fold='train' THEN 'selection' ELSE f.fold END AS partition
FROM player_matches p JOIN match_folds f USING(match_id), split_boundaries b
WHERE f.fold!='test'
GROUP BY p.match_id, f.fold, b.discovery_end;
