SELECT
    hero_id,
    wealth_bin,
    relative_state,
    item_id,
    count(*) AS purchases,
    sum(won::INTEGER) AS wins
FROM experiment_observations
GROUP BY hero_id, wealth_bin, relative_state, item_id
ORDER BY hero_id, wealth_bin, relative_state, item_id;
