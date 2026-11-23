SELECT
    p.match_id,
    p.team_id,
    list_sort(list(p.hero_id)) AS hero_ids
FROM player_matches AS p
GROUP BY p.match_id, p.team_id
ORDER BY p.match_id, p.team_id;
