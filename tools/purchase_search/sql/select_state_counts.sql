WITH distinct_states AS (
    SELECT DISTINCT
        match_id,
        hero_id,
        wealth_bin,
        relative_state,
        won
    FROM experiment_observations
)

SELECT
    hero_id,
    wealth_bin,
    relative_state,
    count(*) AS matches,
    sum(won::INTEGER) AS wins
FROM distinct_states
GROUP BY hero_id, wealth_bin, relative_state
ORDER BY hero_id, wealth_bin, relative_state;
