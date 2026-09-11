CREATE OR REPLACE TABLE compositions AS
SELECT
    match_id,
    team_id,
    list_sort(list(hero_id)) AS hero_ids
FROM player_matches
GROUP BY match_id, team_id;
