WITH match_sizes AS (
    SELECT count(*) AS player_count
    FROM player_matches AS p
    INNER JOIN discovery_partitions AS d ON p.match_id = d.match_id
    GROUP BY p.match_id
)

SELECT DISTINCT player_count FROM match_sizes;
