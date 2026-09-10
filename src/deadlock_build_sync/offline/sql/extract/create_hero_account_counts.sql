CREATE TABLE hero_account_counts AS
SELECT hero_id, count(DISTINCT account_id) AS unique_accounts
FROM remote.main.match_player
INNER JOIN eligible_matches USING (match_id)
GROUP BY hero_id;
