CREATE TABLE hero_account_counts AS
SELECT
    p.hero_id,
    count(DISTINCT p.account_id) AS unique_accounts
FROM source_players AS p
INNER JOIN eligible_matches AS e ON p.match_id = e.match_id
GROUP BY p.hero_id;
