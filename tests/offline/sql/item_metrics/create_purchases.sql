CREATE TABLE purchases AS SELECT
    match_id,
    player_slot,
    item_id,
    buy_time,
    duration_s
FROM events_source;
