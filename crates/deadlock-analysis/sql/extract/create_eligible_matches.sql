CREATE OR REPLACE TABLE eligible_matches AS
WITH candidate_matches AS (
    SELECT match_id
    FROM source_players
    WHERE start_time + duration_s * INTERVAL '1 second' <= $as_of::TIMESTAMPTZ
    GROUP BY match_id
    HAVING
        count(*) = 12
        AND count(DISTINCT player_slot) = 12
        AND count(DISTINCT hero_id) = 12
        AND count(*) FILTER (WHERE team = 'Team0') = 6
        AND count(*) FILTER (WHERE team = 'Team1') = 6
        AND bool_and(rewards_eligible IS TRUE)
        AND bool_and(player_match_outcome IN ('Win', 'Loss'))
        AND count(*) FILTER (WHERE player_match_outcome = 'Win') = 6
        AND count(*) FILTER (WHERE player_match_outcome = 'Loss') = 6
)

SELECT p.match_id
FROM source_players AS p
SEMI JOIN candidate_matches AS c ON p.match_id = c.match_id
GROUP BY p.match_id
HAVING count(*) = 12;
