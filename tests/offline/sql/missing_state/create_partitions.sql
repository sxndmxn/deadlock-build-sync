CREATE TABLE discovery_partitions AS
SELECT
    match_id,
    'discovery' AS "partition"
FROM player_matches;
