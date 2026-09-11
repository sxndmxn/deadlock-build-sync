SELECT
    p.hero_id,
    count(*) AS player_matches,
    sum(p.won::INTEGER) AS wins
FROM player_matches AS p
INNER JOIN experiment_matches AS e ON p.match_id = e.match_id
GROUP BY p.hero_id
ORDER BY p.hero_id;
