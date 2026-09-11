CREATE TABLE player_matches (
    match_id BIGINT, player_slot INTEGER, hero_id INTEGER,
    team_id INTEGER, duration_s INTEGER, won BOOLEAN
);
INSERT INTO player_matches VALUES (1, 1, 1, 0, 2000, TRUE);
CREATE TABLE match_folds (match_id BIGINT, fold VARCHAR);
INSERT INTO match_folds VALUES (1, 'train');
CREATE TABLE player_snapshots (
    match_id BIGINT, player_slot INTEGER, stat_time INTEGER, net_worth INTEGER
);
INSERT INTO player_snapshots VALUES
(1, 1, 540, 5000), (1, 1, 900, 8000),
(1, 1, 1200, 12000), (1, 1, 1500, 15000),
(1, 1, 1800, 18000), (1, 1, 1900, 30000);
CREATE TABLE team_snapshots (
    match_id BIGINT, team_id INTEGER, stat_time INTEGER,
    team_net_worth BIGINT, observed_players INTEGER
);
INSERT INTO team_snapshots VALUES
(1, 0, 540, 30000, 6), (1, 1, 540, 30000, 6),
(1, 0, 900, 48000, 6), (1, 1, 900, 48000, 6),
(1, 0, 1200, 72000, 6), (1, 1, 1200, 72000, 6),
(1, 0, 1500, 90000, 6), (1, 1, 1500, 90000, 6),
(1, 0, 1800, 108000, 6), (1, 1, 1800, 108000, 6);
