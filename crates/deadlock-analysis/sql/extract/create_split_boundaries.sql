CREATE OR REPLACE TABLE split_boundaries AS
WITH matches AS (
    SELECT
        match_id,
        min(start_time) AS started
    FROM player_matches
    WHERE average_badge BETWEEN $minimum_badge AND $maximum_badge
    GROUP BY match_id
)

SELECT
    quantile_cont(epoch(started), 0.45) AS discovery_end,
    quantile_cont(epoch(started), 0.6) AS train_end,
    quantile_cont(epoch(started), 0.8) AS validation_end
FROM matches;
