ATTACH ':memory:' AS remote;
CREATE TABLE remote.main.match_player (
    match_id INTEGER,
    player_slot INTEGER,
    team VARCHAR,
    player_match_outcome VARCHAR,
    rewards_eligible BOOLEAN,
    match_mode VARCHAR,
    game_mode VARCHAR,
    start_time TIMESTAMPTZ,
    duration_s INTEGER,
    average_badge INTEGER
);
