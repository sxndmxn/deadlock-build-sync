CREATE TABLE match_folds (match_id INTEGER, fold VARCHAR);
INSERT INTO match_folds VALUES (1, 'train'), (2, 'train'), (3, 'test');
CREATE TABLE player_matches (match_id INTEGER, hero_id INTEGER);
INSERT INTO player_matches VALUES (1, 1), (1, 2), (2, 1), (2, 1), (2, 2), (3, 1);
